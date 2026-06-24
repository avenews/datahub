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


class ZohoBooksSourceConfig(StatefulIngestionConfigBase, DatasetSourceConfigMixin):
    platform: str = "zoho-books"

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
            "Self Client grant token with scope `ZohoBooks.fullaccess.all` "
            "(or finer-grained `ZohoBooks.<module>.READ` scopes)."
        ),
    )
    organization_id: str = Field(
        description=(
            "Zoho Books organization ID. Every Books API call is scoped to a "
            "single organization. Find it in Zoho Books → Settings → Organizations."
        ),
    )
    region: ZohoRegion = Field(
        default=ZohoRegion.US,
        description="Zoho data center region for both API and accounts endpoints.",
    )

    modules_pattern: AllowDenyPattern = Field(
        default=AllowDenyPattern.allow_all(),
        description=(
            "Regex patterns to filter Zoho Books modules by their API name "
            "(e.g. `invoices`, `contacts`, `items`, `bills`, `expenses`)."
        ),
    )
    include_record_counts: bool = Field(
        default=True,
        description=(
            "Emit per-module row counts as a basic dataset profile. The count is "
            "read from `page_context.total` on each list endpoint."
        ),
    )
    sample_size_for_schema: int = Field(
        default=1,
        description=(
            "Number of records to fetch per module when discovering field names. "
            "Zoho Books has no schema introspection endpoint, so fields are derived "
            "from the union of keys present on sampled records."
        ),
    )
    request_timeout_seconds: int = Field(
        default=30,
        description="HTTP timeout for individual Zoho API requests.",
    )

    stateful_ingestion: Optional[StatefulStaleMetadataRemovalConfig] = None
