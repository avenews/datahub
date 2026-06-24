import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

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
from datahub.ingestion.source.zoho_books.zoho_books_config import (
    REGION_TO_ACCOUNTS_DOMAIN,
    REGION_TO_API_DOMAIN,
    ZohoBooksSourceConfig,
)
from datahub.ingestion.source.zoho_books.zoho_books_report import ZohoBooksSourceReport
from datahub.metadata.schema_classes import (
    BooleanTypeClass,
    DataPlatformInstanceClass,
    DatasetProfileClass,
    DatasetPropertiesClass,
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


@dataclass(frozen=True)
class _BooksModule:
    api_name: str
    path: str
    response_key: str
    display_label: str


# Zoho Books exposes a fixed catalog of resources (it has no /settings/modules
# introspection endpoint). The response_key often matches the path, but a few
# resources nest the array under an underscore-cased key.
# Reference: https://www.zoho.com/books/api/v3/
_BOOKS_MODULES: List[_BooksModule] = [
    _BooksModule("invoices", "/books/v3/invoices", "invoices", "Invoices"),
    _BooksModule("contacts", "/books/v3/contacts", "contacts", "Contacts"),
    _BooksModule(
        "customerpayments",
        "/books/v3/customerpayments",
        "customerpayments",
        "Customer Payments",
    ),
    _BooksModule("creditnotes", "/books/v3/creditnotes", "creditnotes", "Credit Notes"),
    _BooksModule("estimates", "/books/v3/estimates", "estimates", "Estimates"),
    _BooksModule("salesorders", "/books/v3/salesorders", "salesorders", "Sales Orders"),
    _BooksModule(
        "recurringinvoices",
        "/books/v3/recurringinvoices",
        "recurring_invoices",
        "Recurring Invoices",
    ),
    _BooksModule("bills", "/books/v3/bills", "bills", "Bills"),
    _BooksModule(
        "vendorpayments",
        "/books/v3/vendorpayments",
        "vendorpayments",
        "Vendor Payments",
    ),
    _BooksModule(
        "vendorcredits", "/books/v3/vendorcredits", "vendorcredits", "Vendor Credits"
    ),
    _BooksModule(
        "purchaseorders",
        "/books/v3/purchaseorders",
        "purchaseorders",
        "Purchase Orders",
    ),
    _BooksModule("expenses", "/books/v3/expenses", "expenses", "Expenses"),
    _BooksModule(
        "recurringexpenses",
        "/books/v3/recurringexpenses",
        "recurring_expenses",
        "Recurring Expenses",
    ),
    _BooksModule("items", "/books/v3/items", "items", "Items"),
    _BooksModule(
        "bankaccounts", "/books/v3/bankaccounts", "bankaccounts", "Bank Accounts"
    ),
    _BooksModule(
        "banktransactions",
        "/books/v3/banktransactions",
        "banktransactions",
        "Bank Transactions",
    ),
    _BooksModule(
        "chartofaccounts",
        "/books/v3/chartofaccounts",
        "chartofaccounts",
        "Chart of Accounts",
    ),
    _BooksModule("journals", "/books/v3/journals", "journals", "Journals"),
    _BooksModule("projects", "/books/v3/projects", "projects", "Projects"),
]


def _infer_type_class(value: Any) -> Any:
    if isinstance(value, bool):
        return BooleanTypeClass
    if isinstance(value, (int, float)):
        return NumberTypeClass
    if isinstance(value, str):
        return StringTypeClass
    return NullTypeClass


@platform_name("Zoho Books", id="zoho-books")
@config_class(ZohoBooksSourceConfig)
@support_status(SupportStatus.INCUBATING)
@capability(SourceCapability.PLATFORM_INSTANCE, "Enabled by default")
@capability(SourceCapability.SCHEMA_METADATA, "Enabled by default")
@capability(
    SourceCapability.DATA_PROFILING,
    "Optional. Emits per-module row counts when `include_record_counts` is true.",
)
@capability(SourceCapability.TEST_CONNECTION, "Enabled by default")
class ZohoBooksSource(StatefulIngestionSourceBase, TestableSource):
    """Ingest Zoho Books modules (Invoices, Contacts, Items, Bills, Expenses, …)
    into DataHub as Dataset entities. Each module's fields are derived by sampling
    records from the list endpoint; optionally a basic profile (record count) is
    emitted per module using `page_context.total`.
    """

    platform = "zoho-books"

    def __init__(self, ctx: PipelineContext, config: ZohoBooksSourceConfig):
        super().__init__(config, ctx)
        self.config = config
        self.report = ZohoBooksSourceReport()
        self._access_token: Optional[str] = None
        self._access_token_expires_at: float = 0.0

    @classmethod
    def create(
        cls, config_dict: Dict[str, Any], ctx: PipelineContext
    ) -> "ZohoBooksSource":
        return cls(ctx, ZohoBooksSourceConfig.parse_obj(config_dict))

    def get_report(self) -> ZohoBooksSourceReport:
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
        # Every Books API call is scoped to a single organization.
        merged_params: Dict[str, Any] = {"organization_id": self.config.organization_id}
        if params:
            merged_params.update(params)
        base = REGION_TO_API_DOMAIN[self.config.region]
        response = requests.get(
            f"{base}{path}",
            params=merged_params,
            headers=self._auth_header(),
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
            config = ZohoBooksSourceConfig.parse_obj_allow_extras(config_dict)
            source = ZohoBooksSource(
                PipelineContext(run_id="zoho-books-test-connection"), config
            )
            source._refresh_access_token()
            # `/books/v3/organizations` is a low-cost authenticated endpoint that
            # proves the refresh token works against the configured region. We use
            # a plain GET (not _api_get) so we don't pass an organization_id filter,
            # which lets us confirm the token without trusting the configured id.
            base = REGION_TO_API_DOMAIN[config.region]
            response = requests.get(
                f"{base}/books/v3/organizations",
                headers=source._auth_header(),
                timeout=config.request_timeout_seconds,
            )
            response.raise_for_status()
            report.basic_connectivity = CapabilityReport(capable=True)
        except Exception as exc:
            report.basic_connectivity = CapabilityReport(
                capable=False,
                failure_reason=str(exc),
            )
        return report

    # ---------- Ingestion --------------------------------------------------

    def get_workunits_internal(self) -> Iterable[MetadataWorkUnit]:
        for module in _BOOKS_MODULES:
            if not self.config.modules_pattern.allowed(module.api_name):
                self.report.modules_skipped_by_pattern.append(module.api_name)
                continue
            try:
                yield from self._emit_module(module)
                self.report.modules_scanned += 1
            except Exception as exc:
                logger.exception(
                    f"Failed to ingest Zoho Books module {module.api_name}: {exc}"
                )
                self.report.modules_failed.append(module.api_name)

    def _fetch_sample(self, module: _BooksModule) -> Dict[str, Any]:
        return self._api_get(
            module.path,
            params={"per_page": max(1, self.config.sample_size_for_schema)},
        )

    def _emit_module(self, module: _BooksModule) -> Iterable[MetadataWorkUnit]:
        dataset_urn = make_dataset_urn_with_platform_instance(
            platform=self.config.platform,
            name=module.api_name,
            platform_instance=self.config.platform_instance,
            env=self.config.env,
        )

        try:
            sample_payload = self._fetch_sample(module)
        except Exception as exc:
            logger.warning(
                f"Could not sample records for Zoho Books module "
                f"{module.api_name}: {exc}"
            )
            self.report.schema_sample_failed.append(module.api_name)
            sample_payload = {}

        records = sample_payload.get(module.response_key) or []
        if not isinstance(records, list):
            records = []

        yield MetadataChangeProposalWrapper(
            entityUrn=dataset_urn,
            aspect=DatasetPropertiesClass(
                name=module.display_label,
                qualifiedName=module.api_name,
                customProperties={
                    "moduleApiName": module.api_name,
                    "moduleDisplayLabel": module.display_label,
                    "organizationId": self.config.organization_id,
                },
            ),
        ).as_workunit()

        yield MetadataChangeProposalWrapper(
            entityUrn=dataset_urn,
            aspect=SubTypesClass(typeNames=["Zoho Books Module"]),
        ).as_workunit()

        schema_fields = self._derive_schema_fields(records)
        if schema_fields:
            yield MetadataChangeProposalWrapper(
                entityUrn=dataset_urn,
                aspect=SchemaMetadataClass(
                    schemaName=module.api_name,
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
            row_count = self._extract_row_count(sample_payload)
            if row_count is None:
                # Fall back to a lightweight call with per_page=1 just for the count.
                row_count = self._fetch_record_count(module)
            if row_count is not None:
                yield MetadataChangeProposalWrapper(
                    entityUrn=dataset_urn,
                    aspect=DatasetProfileClass(
                        timestampMillis=int(time.time() * 1000),
                        rowCount=row_count,
                        columnCount=len(schema_fields),
                    ),
                ).as_workunit()

    @staticmethod
    def _extract_row_count(payload: Dict[str, Any]) -> Optional[int]:
        page_context = (
            payload.get("page_context") if isinstance(payload, dict) else None
        )
        if not isinstance(page_context, dict):
            return None
        total = page_context.get("total")
        if total is None:
            return None
        try:
            return int(total)
        except (TypeError, ValueError):
            return None

    def _fetch_record_count(self, module: _BooksModule) -> Optional[int]:
        try:
            payload = self._api_get(module.path, params={"per_page": 1})
        except Exception as exc:
            logger.warning(
                f"Could not fetch record count for Zoho Books module "
                f"{module.api_name}: {exc}"
            )
            self.report.record_count_failed.append(module.api_name)
            return None
        return self._extract_row_count(payload)

    def _derive_schema_fields(
        self, records: List[Dict[str, Any]]
    ) -> List[SchemaFieldClass]:
        # Zoho Books has no schema endpoint, so we union the keys across the
        # sampled records and infer the type from the first non-null value seen.
        ordered_fields: Dict[str, Any] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            for key, value in record.items():
                if key in ordered_fields and ordered_fields[key] is not None:
                    continue
                ordered_fields[key] = value

        schema_fields: List[SchemaFieldClass] = []
        for name, sample_value in ordered_fields.items():
            type_class = _infer_type_class(sample_value)
            native_type = (
                type(sample_value).__name__ if sample_value is not None else "unknown"
            )
            schema_fields.append(
                SchemaFieldClass(
                    fieldPath=name,
                    type=SchemaFieldDataTypeClass(type=type_class()),
                    nativeDataType=native_type,
                    nullable=True,
                )
            )
        return schema_fields
