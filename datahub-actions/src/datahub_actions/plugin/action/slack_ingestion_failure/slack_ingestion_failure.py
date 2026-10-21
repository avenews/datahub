import json
import logging
from typing import Optional

from pydantic import Field, SecretStr, field_validator
from ratelimit import limits, sleep_and_retry
from slack_bolt import App
from slack_sdk import WebClient

from datahub.configuration.common import ConfigModel
from datahub.metadata.schema_classes import MetadataChangeLogClass
from datahub_actions.action.action import Action
from datahub_actions.event.event_envelope import EventEnvelope
from datahub_actions.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

FAILED_STATUSES = {"FAILURE", "TIMEOUT", "CANCELLED", "ABORTED"}
EXECUTION_REQUEST_ENTITY = "dataHubExecutionRequest"
ADMIN_LINKS = {
    "dataHubPolicy": "/settings/permissions/policies",
    "dataHubRole": "/settings/permissions/roles",
    "dataHubAccessToken": "/settings/tokens",
    "dataHubSecret": "/ingestion/secrets",
    "dataHubIngestionSource": "/ingestion",
}


@sleep_and_retry  # type: ignore[misc]
@limits(calls=1, period=1)  # type: ignore[misc]
def post_message(client: WebClient, token: str, channel: str, text: str) -> None:
    client.chat_postMessage(token=token, channel=channel, text=text)


class SlackIngestionFailureConfig(ConfigModel):
    bot_token: SecretStr = Field(description="Slack bot token (xoxb-...).")
    signing_secret: SecretStr = Field(description="Slack app signing secret.")
    default_channel: str = Field(description="Slack channel ID or name to post to.")
    base_url: str = Field(
        default="http://localhost:9002",
        description="Public DataHub URL used to build links in messages.",
    )

    @field_validator("default_channel", "base_url")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # Unset ${ENV_VAR} substitutions resolve to an empty string, which would
        # otherwise only surface later as a Slack API error on the first event.
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("bot_token", "signing_secret")
    @classmethod
    def _secret_not_blank(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value


class SlackIngestionFailureAction(Action):
    @classmethod
    def create(cls, config_dict: dict, ctx: PipelineContext) -> "Action":
        config = SlackIngestionFailureConfig.model_validate(config_dict or {})
        return cls(config, ctx)

    def __init__(self, config: SlackIngestionFailureConfig, ctx: PipelineContext):
        self.config = config
        self.ctx = ctx
        self.app = App(
            token=config.bot_token.get_secret_value(),
            signing_secret=config.signing_secret.get_secret_value(),
        )

    def _run_text(self, event: MetadataChangeLogClass) -> Optional[str]:
        if event.aspect is None:
            return None
        try:
            status = str(json.loads(event.aspect.value).get("status", "UNKNOWN"))
        except (ValueError, AttributeError):
            logger.warning("Unparseable execution result for %s", event.entityUrn)
            return None
        emoji = (
            ":rotating_light:" if status in FAILED_STATUSES else ":white_check_mark:"
        )
        link = f"{self.config.base_url.rstrip('/')}/ingestion"
        return (
            f"{emoji} Ingestion run *{status}* ({event.entityUrn}). "
            f"<{link}|View ingestion runs>"
        )

    def _admin_text(self, event: MetadataChangeLogClass) -> str:
        base = self.config.base_url.rstrip("/")
        link = ADMIN_LINKS.get(event.entityType)
        target = (
            f"<{base}{link}|{event.entityUrn}>"
            if link
            else f"<{base}/{event.entityType}/{event.entityUrn}|{event.entityUrn}>"
        )
        # Only metadata about the change is posted, never the aspect payload,
        # because aspects such as secrets and access tokens carry sensitive values.
        return (
            f":shield: Admin change: *{event.aspectName}* {str(event.changeType).lower()} "
            f"on {event.entityType} {target}"
        )

    def name(self) -> str:
        return "SlackIngestionFailureAction"

    def act(self, event: EventEnvelope) -> None:
        try:
            if event.event_type != "MetadataChangeLogEvent_v1":
                return
            assert isinstance(event.event, MetadataChangeLogClass)
            if event.event.entityType == EXECUTION_REQUEST_ENTITY:
                text = self._run_text(event.event)
            else:
                text = self._admin_text(event.event)
            if text:
                post_message(
                    client=self.app.client,
                    token=self.config.bot_token.get_secret_value(),
                    channel=self.config.default_channel,
                    text=text,
                )
        except Exception:
            logger.exception("Failed to post Slack notification")

    def close(self) -> None:
        pass
