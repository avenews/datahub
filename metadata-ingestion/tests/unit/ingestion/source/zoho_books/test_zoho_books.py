"""Unit tests for the Zoho Books ingestion source."""

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from pydantic import SecretStr, ValidationError

from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.source.zoho_books.zoho_books_config import (
    REGION_TO_ACCOUNTS_DOMAIN,
    REGION_TO_API_DOMAIN,
    ZohoBooksSourceConfig,
    ZohoRegion,
)
from datahub.ingestion.source.zoho_books.zoho_books_source import ZohoBooksSource


def _build_config(**overrides: Any) -> ZohoBooksSourceConfig:
    base: Dict[str, Any] = {
        "client_id": "1000.ABCDEF",
        "client_secret": SecretStr("secret-client"),
        "refresh_token": SecretStr("secret-refresh"),
        "organization_id": "60000000000",
    }
    base.update(overrides)
    return ZohoBooksSourceConfig(**base)


# ---------- Config -----------------------------------------------------------


def test_config_defaults():
    config = _build_config()
    assert config.platform == "zoho-books"
    assert config.region is ZohoRegion.US
    assert config.include_record_counts is True
    assert config.modules_pattern.allowed("invoices") is True


def test_config_rejects_unknown_region():
    with pytest.raises(ValidationError):
        _build_config(region="MARS")


def test_region_maps_cover_all_regions():
    for region in ZohoRegion:
        assert region in REGION_TO_API_DOMAIN
        assert region in REGION_TO_ACCOUNTS_DOMAIN


def test_config_requires_credentials():
    with pytest.raises(ValidationError):
        ZohoBooksSourceConfig(  # type: ignore[call-arg]
            client_secret=SecretStr("x"),
            refresh_token=SecretStr("y"),
            organization_id="60000000000",
        )


def test_config_requires_organization_id():
    with pytest.raises(ValidationError):
        ZohoBooksSourceConfig(  # type: ignore[call-arg]
            client_id="1000.ABCDEF",
            client_secret=SecretStr("x"),
            refresh_token=SecretStr("y"),
        )


# ---------- Source -----------------------------------------------------------


def _new_source(**overrides: Any) -> ZohoBooksSource:
    return ZohoBooksSource(
        PipelineContext(run_id="zoho-books-test"), _build_config(**overrides)
    )


def test_derive_schema_fields_infers_types_from_sample():
    source = _new_source()
    fields = source._derive_schema_fields(
        [
            {
                "invoice_id": "abc",
                "total": 12.5,
                "is_emailed": True,
                "balance": None,
            },
            {"customer_name": "Acme"},
        ]
    )
    paths = {f.fieldPath: f for f in fields}
    assert set(paths) == {
        "invoice_id",
        "total",
        "is_emailed",
        "balance",
        "customer_name",
    }
    assert paths["invoice_id"].type.type.__class__.__name__ == "StringTypeClass"
    assert paths["total"].type.type.__class__.__name__ == "NumberTypeClass"
    assert paths["is_emailed"].type.type.__class__.__name__ == "BooleanTypeClass"
    # `balance` was None in the only record where it appeared, so type is unknown.
    assert paths["balance"].type.type.__class__.__name__ == "NullTypeClass"


def test_derive_schema_fields_handles_empty_input():
    source = _new_source()
    assert source._derive_schema_fields([]) == []


def test_extract_row_count_reads_page_context():
    assert (
        ZohoBooksSource._extract_row_count({"page_context": {"total": "42", "page": 1}})
        == 42
    )


def test_extract_row_count_returns_none_when_missing():
    assert ZohoBooksSource._extract_row_count({}) is None
    assert ZohoBooksSource._extract_row_count({"page_context": {}}) is None
    assert (
        ZohoBooksSource._extract_row_count({"page_context": {"total": "not-a-number"}})
        is None
    )


def _captured_module_workunits(
    source: ZohoBooksSource,
    payloads: Dict[str, Dict[str, Any]],
) -> List[Any]:
    def fake_api_get(path: str, params: Dict[str, Any] = None):  # type: ignore[assignment]
        return payloads.get(path, {})

    with patch.object(source, "_api_get", side_effect=fake_api_get):
        return list(source.get_workunits_internal())


def test_modules_pattern_filters_modules():
    source = _new_source(
        modules_pattern={"allow": ["^invoices$"]},
        include_record_counts=False,
    )
    work_units = _captured_module_workunits(
        source,
        payloads={
            "/books/v3/invoices": {
                "invoices": [
                    {"invoice_id": "INV-1", "total": 100, "customer_name": "Acme"}
                ]
            }
        },
    )

    assert source.report.modules_scanned == 1
    # Every non-`invoices` module ends up in the skipped list.
    assert "contacts" in source.report.modules_skipped_by_pattern
    # Properties + SubTypes + Schema for the single included module
    assert len(work_units) == 3


def test_record_count_emitted_from_page_context():
    source = _new_source(
        modules_pattern={"allow": ["^invoices$"]},
    )
    payloads = {
        "/books/v3/invoices": {
            "invoices": [{"invoice_id": "INV-1"}],
            "page_context": {"total": 17},
        }
    }
    units = _captured_module_workunits(source, payloads)

    profile_units = [
        u
        for u in units
        if u.metadata.aspect.__class__.__name__ == "DatasetProfileClass"
    ]
    assert len(profile_units) == 1
    assert profile_units[0].metadata.aspect.rowCount == 17


def test_recurring_invoices_uses_underscore_response_key():
    source = _new_source(
        modules_pattern={"allow": ["^recurringinvoices$"]},
        include_record_counts=False,
    )
    units = _captured_module_workunits(
        source,
        payloads={
            "/books/v3/recurringinvoices": {
                "recurring_invoices": [
                    {"recurring_invoice_id": "RI-1", "status": "active"}
                ]
            }
        },
    )
    schema_units = [
        u
        for u in units
        if u.metadata.aspect.__class__.__name__ == "SchemaMetadataClass"
    ]
    assert len(schema_units) == 1
    field_paths = {f.fieldPath for f in schema_units[0].metadata.aspect.fields}
    assert field_paths == {"recurring_invoice_id", "status"}
