"""Run Great Expectations checks on source data and publish results to DataHub as assertions."""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from typing import Any, Callable, Dict, List

import pandas as pd
import yaml

import great_expectations as gx
from datahub.emitter.mce_builder import (
    make_assertion_urn,
    make_dataset_urn,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    AssertionInfoClass,
    AssertionResultClass,
    AssertionResultTypeClass,
    AssertionRunEventClass,
    AssertionRunStatusClass,
    AssertionSourceClass,
    AssertionSourceTypeClass,
    AssertionTypeClass,
    CustomAssertionInfoClass,
)

logger = logging.getLogger("dq")

_ENV_DEFAULT = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _expand_env(text: str) -> str:
    return _ENV_DEFAULT.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), text)


def load_mongodb(ds: Dict[str, Any]) -> pd.DataFrame:
    from pymongo import MongoClient

    client: Any = MongoClient(os.environ[ds["uri_env"]])
    cursor = client[ds["database"]][ds["collection"]].find().limit(ds.get("sample_size", 10000))
    docs = list(cursor)
    for doc in docs:
        doc["_id"] = str(doc["_id"])
    return pd.DataFrame(docs)


# Register new source loaders here (each returns a DataFrame).
LOADERS: Dict[str, Callable[[Dict[str, Any]], pd.DataFrame]] = {
    "mongodb": load_mongodb,
}


def _assertion_id(dataset_urn: str, check: Dict[str, Any]) -> str:
    key = f"{dataset_urn}|{check['expectation']}|{json.dumps(check.get('kwargs', {}), sort_keys=True)}"
    return hashlib.md5(key.encode()).hexdigest()  # noqa: S324 - stable id, not security


def _summarize_result(
    result: Dict[str, Any], kwargs: Dict[str, Any], expected_format: Any, success: bool
) -> Dict[str, str]:
    """Human-readable fields shown in the DataHub assertion result popover."""
    summary: Dict[str, str] = {}
    if expected_format:
        summary["Expected format"] = str(expected_format)
    required = float(kwargs.get("mostly", 1.0)) * 100
    total = result.get("element_count")
    bad = result.get("unexpected_count")
    if total:
        valid_pct = 100 - float(result.get("unexpected_percent_total") or 0)
        summary["Rows checked"] = str(total)
        summary["Rows failing"] = str(bad or 0)
        summary["Valid"] = f"{valid_pct:.1f}%"
        summary["Quality gate"] = f"{'PASSED' if success else 'FAILED'} (requires {required:g}% valid)"
        samples = result.get("partial_unexpected_list") or []
        if samples:
            summary["Example invalid values"] = ", ".join(str(s) for s in samples[:5])
    else:
        summary["Quality gate"] = "PASSED" if success else "FAILED"
        summary["Details"] = json.dumps(result, default=str)[:500]
    return summary


def run_dataset(ds: Dict[str, Any], emitter: DatahubRestEmitter, run_id: str) -> int:
    dataset_urn = make_dataset_urn(platform=ds["platform"], name=ds["urn_name"])
    logger.info("Validating %s", dataset_urn)
    df = LOADERS[ds["source"]](ds)
    gx_df = gx.from_pandas(df)
    failures = 0

    for check in ds["checks"]:
        name, kwargs = check["expectation"], check.get("kwargs", {})
        display_name = (
            check.get("name") or name.replace("expect_", "", 1).replace("_", " ").capitalize()
        )
        description = check.get("description") or display_name
        column = kwargs.get("column")
        try:
            if column is not None and column not in df.columns:
                raise KeyError(f"Column '{column}' not found in sampled documents")
            result = getattr(gx_df, name)(**kwargs)
            success = bool(result.success)
            native = _summarize_result(result.result, kwargs, check.get("format"), success)
        except Exception as exc:
            logger.exception("Check %s failed to execute", name)
            success = False
            native = {"Quality gate": "FAILED", "Reason": str(exc).strip("'\"")}
        failures += 0 if success else 1
        logger.info("%s %s %s -> %s", ds["urn_name"], name, kwargs, "PASS" if success else "FAIL")

        assertion_urn = make_assertion_urn(_assertion_id(dataset_urn, check))
        emitter.emit(
            MetadataChangeProposalWrapper(
                entityUrn=assertion_urn,
                aspect=AssertionInfoClass(
                    type=AssertionTypeClass.CUSTOM,
                    customProperties={"expectation": name, **{k: str(v) for k, v in kwargs.items()}},
                    description=description,
                    source=AssertionSourceClass(type=AssertionSourceTypeClass.EXTERNAL),
                    customAssertion=CustomAssertionInfoClass(
                        type=display_name,
                        entity=dataset_urn,
                        logic=json.dumps(kwargs, sort_keys=True),
                    ),
                ),
            )
        )
        emitter.emit(
            MetadataChangeProposalWrapper(
                entityUrn=assertion_urn,
                aspect=AssertionRunEventClass(
                    timestampMillis=int(time.time() * 1000),
                    runId=run_id,
                    asserteeUrn=dataset_urn,
                    assertionUrn=assertion_urn,
                    status=AssertionRunStatusClass.COMPLETE,
                    result=AssertionResultClass(
                        type=AssertionResultTypeClass.SUCCESS if success else AssertionResultTypeClass.FAILURE,
                        nativeResults=native,
                    ),
                ),
            )
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "checks.yml"))
    parser.add_argument("--only", help="Only run datasets with this source type")
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Re-run every N seconds instead of exiting after one run (used by the dq-runner container)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    while True:
        # Reload each cycle so edits to checks.yml apply without restarting the container.
        with open(args.config) as f:
            cfg = yaml.safe_load(_expand_env(f.read()))

        emitter = DatahubRestEmitter(
            gms_server=cfg["datahub"]["server"],
            token=os.environ.get(cfg["datahub"].get("token_env", "")) or None,
        )
        run_id = f"gx-{uuid.uuid4()}"
        total_failures = 0
        for ds in cfg["datasets"]:
            if args.only and ds["source"] != args.only:
                continue
            try:
                total_failures += run_dataset(ds, emitter, run_id)
            except Exception:
                logger.exception("Dataset %s could not be validated", ds["urn_name"])
                total_failures += 1
        if not args.interval:
            return 1 if total_failures else 0
        logger.info("Run finished with %d failure(s); next run in %ds", total_failures, args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
