import json
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from datahub.metadata.schema_classes import GenericAspectClass, MetadataChangeLogClass
from datahub_actions.event.event_envelope import EventEnvelope
from datahub_actions.plugin.action.slack_ingestion_failure.slack_ingestion_failure import (
    SlackIngestionFailureAction,
)
from tests.unit.test_helpers import pipeline_context

MODULE = "datahub_actions.plugin.action.slack_ingestion_failure.slack_ingestion_failure"

VALID_CONFIG = {
    "bot_token": "xoxb-test",
    "signing_secret": "secret",
    "default_channel": "C123",
    "base_url": "https://datahub.example.com/",
}


def _mcl(
    entity_type: str, aspect_name: str, aspect: Optional[dict] = None
) -> EventEnvelope:
    event = MetadataChangeLogClass(
        entityType=entity_type,
        changeType="UPSERT",
        entityUrn=f"urn:li:{entity_type}:abc",
        aspectName=aspect_name,
        aspect=GenericAspectClass(
            value=json.dumps(aspect or {}).encode(), contentType="application/json"
        ),
    )
    return EventEnvelope("MetadataChangeLogEvent_v1", event, {})


@pytest.fixture
def action():
    with patch(f"{MODULE}.App") as app, patch(f"{MODULE}.post_message") as post:
        instance = SlackIngestionFailureAction.create(VALID_CONFIG, pipeline_context)
        instance.app = app.return_value
        instance.post = post  # type: ignore[attr-defined]
        yield instance


@pytest.mark.parametrize("field", ["bot_token", "signing_secret", "default_channel"])
def test_create_rejects_blank_values(field):
    with patch(f"{MODULE}.App"), pytest.raises(ValidationError):
        SlackIngestionFailureAction.create(
            {**VALID_CONFIG, field: ""}, pipeline_context
        )


@pytest.mark.parametrize(
    "status,emoji",
    [("FAILURE", ":rotating_light:"), ("SUCCESS", ":white_check_mark:")],
)
def test_all_run_results_are_posted(action, status, emoji):
    action.act(
        _mcl(
            "dataHubExecutionRequest",
            "dataHubExecutionRequestResult",
            {"status": status},
        )
    )
    text = action.post.call_args.kwargs["text"]
    assert emoji in text and status in text


def test_admin_change_never_includes_aspect_payload(action):
    action.act(
        _mcl("dataHubSecret", "dataHubSecretValue", {"value": "super-secret-value"})
    )
    text = action.post.call_args.kwargs["text"]
    assert "super-secret-value" not in text
    assert "https://datahub.example.com/ingestion/secrets" in text


def test_slack_failure_does_not_raise(action):
    action.post.side_effect = RuntimeError("slack down")
    action.act(_mcl("dataHubPolicy", "dataHubPolicyInfo"))


def test_other_event_types_ignored(action):
    action.act(EventEnvelope("EntityChangeEvent_v1", MagicMock(), {}))
    action.post.assert_not_called()
