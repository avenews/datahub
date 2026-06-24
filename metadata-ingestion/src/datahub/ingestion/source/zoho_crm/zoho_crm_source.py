import logging
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
from datahub.ingestion.source.state.stateful_ingestion_base import (
    StatefulIngestionSourceBase,
)
from datahub.ingestion.source.zoho_crm.zoho_crm_config import (
    REGION_TO_ACCOUNTS_DOMAIN,
    REGION_TO_API_DOMAIN,
    ZohoCRMSourceConfig,
)
from datahub.ingestion.source.zoho_crm.zoho_crm_report import ZohoCRMSourceReport
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
)

logger = logging.getLogger(__name__)

# Map Zoho field `data_type` strings → DataHub schema type classes.
# Reference: https://www.zoho.com/crm/developer/docs/api/v2/field-meta.html
_ZOHO_TYPE_TO_DATAHUB: Dict[str, Type] = {
    "text": StringTypeClass,
    "textarea": StringTypeClass,
    "email": StringTypeClass,
    "phone": StringTypeClass,
    "website": StringTypeClass,
    "picklist": StringTypeClass,
    "multiselectpicklist": StringTypeClass,
    "lookup": StringTypeClass,
    "userlookup": StringTypeClass,
    "ownerlookup": StringTypeClass,
    "autonumber": StringTypeClass,
    "formula": StringTypeClass,
    "subform": StringTypeClass,
    "integer": NumberTypeClass,
    "bigint": NumberTypeClass,
    "currency": NumberTypeClass,
    "double": NumberTypeClass,
    "percent": NumberTypeClass,
    "boolean": BooleanTypeClass,
    "date": DateTypeClass,
    "datetime": DateTypeClass,
}


@platform_name("Zoho CRM", id="zoho-crm")
@config_class(ZohoCRMSourceConfig)
@support_status(SupportStatus.INCUBATING)
@capability(SourceCapability.PLATFORM_INSTANCE, "Enabled by default")
@capability(SourceCapability.SCHEMA_METADATA, "Enabled by default")
@capability(
    SourceCapability.DATA_PROFILING,
    "Optional. Emits per-module row counts when `include_record_counts` is true.",
)
@capability(SourceCapability.TEST_CONNECTION, "Enabled by default")
class ZohoCRMSource(StatefulIngestionSourceBase, TestableSource):
    """Ingest Zoho CRM modules (Leads, Contacts, Deals, Accounts, custom modules, …)
    into DataHub as Dataset entities. Each module's fields are emitted as schema
    metadata; optionally a basic profile (record count) is emitted per module.
    """

    platform = "zoho-crm"

    def __init__(self, ctx: PipelineContext, config: ZohoCRMSourceConfig):
        super().__init__(config, ctx)
        self.config = config
        self.report = ZohoCRMSourceReport()
        self._access_token: Optional[str] = None
        self._access_token_expires_at: float = 0.0

    @classmethod
    def create(
        cls, config_dict: Dict[str, Any], ctx: PipelineContext
    ) -> "ZohoCRMSource":
        return cls(ctx, ZohoCRMSourceConfig.parse_obj(config_dict))

    def get_report(self) -> ZohoCRMSourceReport:
        return self.report

    # ---------- Auth & HTTP ------------------------------------------------

    def _refresh_access_token(self) -> str:
        accounts_url = REGION_TO_ACCOUNTS_DOMAIN[self.config.region]
        params = {
            "refresh_token": self.config.refresh_token.get_secret_value(),
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret.get_secret_value(),
            "grant_type": "refresh_token",
        }
        response = requests.post(
            f"{accounts_url}/oauth/v2/token",
            params=params,
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if "access_token" not in payload:
            raise RuntimeError(
                f"Zoho token refresh failed: {payload.get('error') or payload}"
            )
        self._access_token = payload["access_token"]
        # Subtract a small safety margin so we refresh before Zoho actually expires it.
        self._access_token_expires_at = (
            time.time() + int(payload.get("expires_in", 3600)) - 60
        )
        return self._access_token

    def _auth_header(self) -> Dict[str, str]:
        if not self._access_token or time.time() >= self._access_token_expires_at:
            self._refresh_access_token()
        return {"Authorization": f"Zoho-oauthtoken {self._access_token}"}

    def _api_get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        base = REGION_TO_API_DOMAIN[self.config.region]
        response = requests.get(
            f"{base}{path}",
            params=params,
            headers=self._auth_header(),
            timeout=self.config.request_timeout_seconds,
        )
        if response.status_code == 204:
            return {}
        response.raise_for_status()
        return response.json()

    def _api_post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        base = REGION_TO_API_DOMAIN[self.config.region]
        headers = {**self._auth_header(), "Content-Type": "application/json"}
        response = requests.post(
            f"{base}{path}",
            json=body,
            headers=headers,
            timeout=self.config.request_timeout_seconds,
        )
        if response.status_code == 204:
            return {}
        response.raise_for_status()
        return response.json()

    # ---------- TestableSource --------------------------------------------

    @staticmethod
    def test_connection(config_dict: Dict[str, Any]) -> TestConnectionReport:
        report = TestConnectionReport()
        try:
            config = ZohoCRMSourceConfig.parse_obj_allow_extras(config_dict)
            source = ZohoCRMSource(
                PipelineContext(run_id="zoho-crm-test-connection"), config
            )
            source._refresh_access_token()
            # `/crm/v2/org` is a low-cost authenticated endpoint that proves the
            # refresh token works against the configured region.
            source._api_get("/crm/v2/org")
            report.basic_connectivity = CapabilityReport(capable=True)
        except Exception as exc:
            report.basic_connectivity = CapabilityReport(
                capable=False,
                failure_reason=str(exc),
            )
        return report

    # ---------- Ingestion --------------------------------------------------

    def get_workunits_internal(self) -> Iterable[MetadataWorkUnit]:
        for module in self._fetch_modules():
            api_name = module.get("api_name")
            if not api_name:
                continue
            if not self.config.modules_pattern.allowed(api_name):
                self.report.modules_skipped_by_pattern.append(api_name)
                continue
            if module.get("deprecated") and not self.config.include_deprecated_modules:
                self.report.modules_skipped_deprecated.append(api_name)
                continue
            try:
                yield from self._emit_module(api_name, module)
                self.report.modules_scanned += 1
            except Exception as exc:
                logger.exception(f"Failed to ingest Zoho module {api_name}: {exc}")
                self.report.modules_failed.append(api_name)

    def _fetch_modules(self) -> List[Dict[str, Any]]:
        return self._api_get("/crm/v2/settings/modules").get("modules", [])

    def _fetch_fields(self, module_api_name: str) -> List[Dict[str, Any]]:
        return self._api_get(
            "/crm/v2/settings/fields", params={"module": module_api_name}
        ).get("fields", [])

    def _fetch_record_count(self, module_api_name: str) -> Optional[int]:
        try:
            payload = self._api_post(
                "/crm/v2/coql",
                {"select_query": f"select count() from {module_api_name}"},
            )
        except Exception as exc:
            logger.warning(
                f"Could not fetch record count for Zoho module {module_api_name}: {exc}"
            )
            self.report.record_count_failed.append(module_api_name)
            return None
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if rows and isinstance(rows[0], dict) and "count" in rows[0]:
            try:
                return int(rows[0]["count"])
            except (TypeError, ValueError):
                return None
        return None

    def _emit_module(
        self, api_name: str, module: Dict[str, Any]
    ) -> Iterable[MetadataWorkUnit]:
        dataset_urn = make_dataset_urn_with_platform_instance(
            platform=self.config.platform,
            name=api_name,
            platform_instance=self.config.platform_instance,
            env=self.config.env,
        )
        display_name = (
            module.get("plural_label") or module.get("module_name") or api_name
        )

        yield MetadataChangeProposalWrapper(
            entityUrn=dataset_urn,
            aspect=DatasetPropertiesClass(
                name=display_name,
                qualifiedName=api_name,
                description=module.get("description") or None,
                customProperties={
                    "moduleApiName": api_name,
                    "modulePluralLabel": str(module.get("plural_label") or ""),
                    "moduleSingularLabel": str(module.get("singular_label") or ""),
                    "isCustomModule": str(
                        module.get("generated_type") == "custom"
                    ).lower(),
                },
            ),
        ).as_workunit()

        yield MetadataChangeProposalWrapper(
            entityUrn=dataset_urn,
            aspect=SubTypesClass(typeNames=["Zoho CRM Module"]),
        ).as_workunit()

        fields = self._fetch_fields(api_name)
        schema_fields = [
            self._to_schema_field(field) for field in fields if field.get("api_name")
        ]
        if schema_fields:
            yield MetadataChangeProposalWrapper(
                entityUrn=dataset_urn,
                aspect=SchemaMetadataClass(
                    schemaName=api_name,
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

        if self.config.include_record_counts:
            row_count = self._fetch_record_count(api_name)
            if row_count is not None:
                yield MetadataChangeProposalWrapper(
                    entityUrn=dataset_urn,
                    aspect=DatasetProfileClass(
                        timestampMillis=int(time.time() * 1000),
                        rowCount=row_count,
                        columnCount=len(schema_fields),
                    ),
                ).as_workunit()

    def _to_schema_field(self, field: Dict[str, Any]) -> SchemaFieldClass:
        zoho_type = (field.get("data_type") or "").lower()
        type_class = _ZOHO_TYPE_TO_DATAHUB.get(zoho_type, NullTypeClass)
        return SchemaFieldClass(
            fieldPath=field["api_name"],
            type=SchemaFieldDataTypeClass(type=type_class()),
            nativeDataType=zoho_type or "unknown",
            description=field.get("field_label") or field.get("display_label"),
            nullable=not bool(field.get("system_mandatory")),
        )
