from typing import Optional

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


class PostHogSourceConfig(StatefulIngestionConfigBase, DatasetSourceConfigMixin):
    platform: str = "posthog"

    api_token: TransparentSecretStr = Field(
        description=(
            "PostHog personal API key. Create one under "
            "Account > Personal API Keys with at least `project:read`, "
            "`event_definition:read`, and `property_definition:read` scopes."
        ),
    )
    host: str = Field(
        default="https://us.posthog.com",
        description=(
            "PostHog host URL. Use `https://us.posthog.com` for PostHog Cloud US, "
            "`https://eu.posthog.com` for PostHog Cloud EU, or your own self-hosted URL."
        ),
    )

    projects_pattern: AllowDenyPattern = Field(
        default=AllowDenyPattern.allow_all(),
        description=(
            "Regex patterns to filter PostHog projects by their human-readable name."
        ),
    )
    events_pattern: AllowDenyPattern = Field(
        default=AllowDenyPattern.allow_all(),
        description=(
            "Regex patterns to filter event definitions by event name "
            "(e.g. `$pageview`, `signup_completed`)."
        ),
    )
    include_event_volume: bool = Field(
        default=True,
        description=(
            "Emit each event's rolling 30-day occurrence count "
            "(`volume_30_day` from PostHog) as a basic dataset profile."
        ),
    )
    request_timeout_seconds: int = Field(
        default=30,
        description="HTTP timeout for individual PostHog API requests.",
    )

    stateful_ingestion: Optional[StatefulStaleMetadataRemovalConfig] = None
