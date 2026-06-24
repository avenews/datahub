import json
import logging
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Type

import requests

from datahub.emitter.mce_builder import (
    make_data_platform_urn,
    make_dataplatform_instance_urn,
    make_dataset_urn_with_platform_instance,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.api.decorators import (
    SourceCapability,
    SupportStatus,
    capability,
    config_class,
    platform_name,
    support_status,
)
from datahub.ingestion.api.source import (
    CapabilityReport,
    TestableSource,
    TestConnectionReport,
)
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.ingestion.source.posthog.posthog_config import PostHogSourceConfig
from datahub.ingestion.source.posthog.posthog_report import PostHogSourceReport
from datahub.ingestion.source.state.stateful_ingestion_base import (
    StatefulIngestionSourceBase,
)
from datahub.metadata.schema_classes import (
    BooleanTypeClass,
    DataPlatformInstanceClass,
    DatasetProfileClass,
    DatasetPropertiesClass,
    DateTypeClass,
    NullTypeClass,
    NumberTypeClass,
    OtherSchemaClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
    StringTypeClass,
    SubTypesClass,
    TimeTypeClass,
)

logger = logging.getLogger(__name__)

# Map PostHog `property_type` (Numeric|String|Boolean|DateTime|Duration|null) → DataHub types.
# Reference: https://posthog.com/docs/api/property-definitions
_POSTHOG_TYPE_TO_DATAHUB: Dict[str, Type] = {
    "numeric": NumberTypeClass,
    "string": StringTypeClass,
    "boolean": BooleanTypeClass,
    "datetime": DateTypeClass,
    "duration": TimeTypeClass,
}

# PostHog dataset names use `<sanitized_project>.<event_name>`. The project segment is
# sanitized because project names can contain spaces / symbols that break URN parsing.
_NAME_SANITIZER = re.compile(r"[^A-Za-z0-9_.-]+")


def _sanitize(value: str) -> str:
    return _NAME_SANITIZER.sub("_", value).strip("_") or "project"


@platform_name("PostHog", id="posthog")
@config_class(PostHogSourceConfig)
@support_status(SupportStatus.INCUBATING)
@capability(SourceCapability.PLATFORM_INSTANCE, "Enabled by default")
@capability(SourceCapability.SCHEMA_METADATA, "Enabled by default")
@capability(SourceCapability.DESCRIPTIONS, "Enabled by default")
@capability(
    SourceCapability.DATA_PROFILING,
    "Optional. Emits each event's `volume_30_day` as a basic profile.",
)
@capability(SourceCapability.TEST_CONNECTION, "Enabled by default")
class PostHogSource(StatefulIngestionSourceBase, TestableSource):
    """Ingest PostHog projects, events, and event properties into DataHub.

    Each `(project, event)` pair becomes a Dataset whose schema fields are the
    properties PostHog has observed on that event. Optionally a basic profile
    (`volume_30_day`) is emitted per event.
    """

    platform = "posthog"

    def __init__(self, ctx: PipelineContext, config: PostHogSourceConfig):
        super().__init__(config, ctx)
        self.config = config
        self.report = PostHogSourceReport()

    @classmethod
    def create(
        cls, config_dict: Dict[str, Any], ctx: PipelineContext
    ) -> "PostHogSource":
        return cls(ctx, PostHogSourceConfig.parse_obj(config_dict))

    def get_report(self) -> PostHogSourceReport:
        return self.report

    # ---------- HTTP -------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_token.get_secret_value()}",
            "Accept": "application/json",
        }

    def _api_get(
        self, path_or_url: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else f"{self.config.host.rstrip('/')}{path_or_url}"
        )
        response = requests.get(
            url,
            params=params,
            headers=self._headers(),
            timeout=self.config.request_timeout_seconds,
        )
        if response.status_code == 204:
            return {}
        response.raise_for_status()
        return response.json()

    def _paginate(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Iterable[Dict[str, Any]]:
        page = self._api_get(path, params=params)
        while True:
            for item in page.get("results", []) or []:
                yield item
            next_url = page.get("next")
            if not next_url:
                return
            # PostHog returns absolute URLs for `next` that already include cursor params.
            page = self._api_get(next_url)

    # ---------- TestableSource --------------------------------------------

    @staticmethod
    def test_connection(config_dict: Dict[str, Any]) -> TestConnectionReport:
        report = TestConnectionReport()
        try:
            config = PostHogSourceConfig.parse_obj_allow_extras(config_dict)
            source = PostHogSource(
                PipelineContext(run_id="posthog-test-connection"), config
            )
            # `/api/users/@me/` is a low-cost authenticated endpoint that proves the
            # personal API key works against the configured host.
            source._api_get("/api/users/@me/")
            report.basic_connectivity = CapabilityReport(capable=True)
        except Exception as exc:
            report.basic_connectivity = CapabilityReport(
                capable=False,
                failure_reason=str(exc),
            )
        return report

    # ---------- Ingestion --------------------------------------------------

    def get_workunits_internal(self) -> Iterable[MetadataWorkUnit]:
        for project in self._fetch_projects():
            project_id = project.get("id")
            project_name = project.get("name") or str(project_id)
            if project_id is None:
                continue
            if not self.config.projects_pattern.allowed(project_name):
                self.report.projects_skipped_by_pattern.append(project_name)
                continue
            self.report.projects_scanned += 1
            yield from self._emit_project_events(int(project_id), project_name)

    def _fetch_projects(self) -> List[Dict[str, Any]]:
        return list(self._paginate("/api/projects/"))

    def _fetch_event_definitions(self, project_id: int) -> Iterable[Dict[str, Any]]:
        return self._paginate(f"/api/projects/{project_id}/event_definitions/")

    def _fetch_event_properties(
        self, project_id: int, event_name: str
    ) -> List[Dict[str, Any]]:
        try:
            return list(
                self._paginate(
                    f"/api/projects/{project_id}/property_definitions/",
                    params={"event_names": json.dumps([event_name])},
                )
            )
        except Exception as exc:
            logger.warning(
                f"Could not fetch property definitions for PostHog event "
                f"{project_id}/{event_name}: {exc}"
            )
            self.report.properties_skipped.append(f"{project_id}/{event_name}")
            return []

    def _emit_project_events(
        self, project_id: int, project_name: str
    ) -> Iterable[MetadataWorkUnit]:
        sanitized_project = _sanitize(project_name)
        for event in self._fetch_event_definitions(project_id):
            event_name = event.get("name")
            if not event_name:
                continue
            if not self.config.events_pattern.allowed(event_name):
                self.report.events_skipped_by_pattern.append(event_name)
                continue
            try:
                yield from self._emit_event(
                    project_id, project_name, sanitized_project, event
                )
                self.report.events_scanned += 1
            except Exception as exc:
                logger.exception(
                    f"Failed to ingest PostHog event {project_id}/{event_name}: {exc}"
                )
                self.report.events_failed.append(f"{project_id}/{event_name}")

    def _emit_event(
        self,
        project_id: int,
        project_name: str,
        sanitized_project: str,
        event: Dict[str, Any],
    ) -> Iterable[MetadataWorkUnit]:
        event_name = event["name"]
        dataset_name = f"{sanitized_project}.{event_name}"
        dataset_urn = make_dataset_urn_with_platform_instance(
            platform=self.config.platform,
            name=dataset_name,
            platform_instance=self.config.platform_instance,
            env=self.config.env,
        )

        custom_properties = {
            "projectId": str(project_id),
            "projectName": project_name,
            "eventName": event_name,
        }
        if event.get("last_seen_at"):
            custom_properties["lastSeenAt"] = str(event["last_seen_at"])
        if event.get("volume_30_day") is not None:
            custom_properties["volume30Day"] = str(event["volume_30_day"])
        if event.get("query_usage_30_day") is not None:
            custom_properties["queryUsage30Day"] = str(event["query_usage_30_day"])

        yield MetadataChangeProposalWrapper(
            entityUrn=dataset_urn,
            aspect=DatasetPropertiesClass(
                name=event_name,
                qualifiedName=dataset_name,
                description=event.get("description") or None,
                customProperties=custom_properties,
            ),
        ).as_workunit()

        yield MetadataChangeProposalWrapper(
            entityUrn=dataset_urn,
            aspect=SubTypesClass(typeNames=["PostHog Event"]),
        ).as_workunit()

        properties = self._fetch_event_properties(project_id, event_name)
        schema_fields = [
            self._to_schema_field(prop) for prop in properties if prop.get("name")
        ]
        if schema_fields:
            yield MetadataChangeProposalWrapper(
                entityUrn=dataset_urn,
                aspect=SchemaMetadataClass(
                    schemaName=dataset_name,
                    platform=make_data_platform_urn(self.config.platform),
                    version=0,
                    hash="",
                    platformSchema=OtherSchemaClass(rawSchema=""),
                    fields=schema_fields,
                ),
            ).as_workunit()

        if self.config.platform_instance:
            yield MetadataChangeProposalWrapper(
                entityUrn=dataset_urn,
                aspect=DataPlatformInstanceClass(
                    platform=make_data_platform_urn(self.config.platform),
                    instance=make_dataplatform_instance_urn(
                        self.config.platform, self.config.platform_instance
                    ),
                ),
            ).as_workunit()

        if self.config.include_event_volume:
            volume = event.get("volume_30_day")
            if isinstance(volume, (int, float)):
                yield MetadataChangeProposalWrapper(
                    entityUrn=dataset_urn,
                    aspect=DatasetProfileClass(
                        timestampMillis=int(time.time() * 1000),
                        rowCount=int(volume),
                        columnCount=len(schema_fields),
                    ),
                ).as_workunit()

    def _to_schema_field(self, prop: Dict[str, Any]) -> SchemaFieldClass:
        prop_type = (prop.get("property_type") or "").lower()
        type_class = _POSTHOG_TYPE_TO_DATAHUB.get(prop_type, NullTypeClass)
        return SchemaFieldClass(
            fieldPath=prop["name"],
            type=SchemaFieldDataTypeClass(type=type_class()),
            nativeDataType=prop_type or "unknown",
            description=prop.get("description") or None,
            nullable=True,
        )
