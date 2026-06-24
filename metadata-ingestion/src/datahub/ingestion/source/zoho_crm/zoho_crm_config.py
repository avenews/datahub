from enum import Enum
from typing import Dict, Optional

from pydantic import Field

from datahub.configuration.common import (
    AllowDenyPattern,
    TransparentSecretStr,
)
from datahub.configuration.source_common import DatasetSourceConfigMixin
from datahub.ingestion.source.state.stale_entity_removal_handler import (
    StatefulStaleMetadataRemovalConfig,
)
from datahub.ingestion.source.state.stateful_ingestion_base import (
    StatefulIngestionConfigBase,
)


class ZohoRegion(str, Enum):
    US = "US"
    EU = "EU"
    IN = "IN"
    AU = "AU"
    JP = "JP"
    CN = "CN"


# Zoho operates regional data centers. Auth + API endpoints must use the same region
# as the account that issued the refresh token, otherwise the token is rejected.
REGION_TO_API_DOMAIN: Dict[ZohoRegion, str] = {
    ZohoRegion.US: "https://www.zohoapis.com",
    ZohoRegion.EU: "https://www.zohoapis.eu",
    ZohoRegion.IN: "https://www.zohoapis.in",
    ZohoRegion.AU: "https://www.zohoapis.com.au",
    ZohoRegion.JP: "https://www.zohoapis.jp",
    ZohoRegion.CN: "https://www.zohoapis.com.cn",
}

REGION_TO_ACCOUNTS_DOMAIN: Dict[ZohoRegion, str] = {
    ZohoRegion.US: "https://accounts.zoho.com",
    ZohoRegion.EU: "https://accounts.zoho.eu",
    ZohoRegion.IN: "https://accounts.zoho.in",
    ZohoRegion.AU: "https://accounts.zoho.com.au",
    ZohoRegion.JP: "https://accounts.zoho.jp",
    ZohoRegion.CN: "https://accounts.zoho.com.cn",
}


class ZohoCRMSourceConfig(StatefulIngestionConfigBase, DatasetSourceConfigMixin):
    platform: str = "zoho-crm"

    client_id: str = Field(
        description=(
            "Zoho OAuth client ID. Create a Self Client in the Zoho API Console "
            "(https://api-console.zoho.com) and copy the Client ID."
        ),
    )
    client_secret: TransparentSecretStr = Field(
        description="Zoho OAuth client secret from the same Self Client."
    )
    refresh_token: TransparentSecretStr = Field(
        description=(
            "Zoho OAuth refresh token. Generate it once by exchanging a "
            "Self Client grant token with scope `ZohoCRM.modules.ALL,"
            "ZohoCRM.settings.ALL,ZohoCRM.coql.READ`."
        ),
    )
    region: ZohoRegion = Field(
        default=ZohoRegion.US,
        description="Zoho data center region for both API and accounts endpoints.",
    )

    modules_pattern: AllowDenyPattern = Field(
        default=AllowDenyPattern.allow_all(),
        description=(
            "Regex patterns to filter Zoho CRM modules by their API name "
            "(e.g. `Leads`, `Contacts`, `Deals`, custom modules like `CustomModule1`)."
        ),
    )
    include_deprecated_modules: bool = Field(
        default=False,
        description="Whether to ingest modules that Zoho marks as deprecated.",
    )
    include_record_counts: bool = Field(
        default=True,
        description=(
            "Emit per-module row counts as a basic dataset profile. "
            "Requires the `ZohoCRM.coql.READ` scope on the refresh token."
        ),
    )
    request_timeout_seconds: int = Field(
        default=30,
        description="HTTP timeout for individual Zoho API requests.",
    )

    stateful_ingestion: Optional[StatefulStaleMetadataRemovalConfig] = None
