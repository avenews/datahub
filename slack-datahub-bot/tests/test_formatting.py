from bot.datahub_auth import DataHubIdentity
from bot.formatting import (
    disconnected_message,
    not_connected_message,
    status_message,
    token_rejected_message,
    token_saved_message,
    truncate_for_slack,
    working_on_it_message,
)


def test_not_connected_message_mentions_settings_path():
    text = not_connected_message()
    assert "Access Tokens" in text
    assert "/datahub-connect" in text
    assert "**" not in text  # must be Slack mrkdwn, not Markdown bold


def test_token_saved_message_includes_identity():
    identity = DataHubIdentity(username="jane.doe", urn="urn:li:corpuser:jane.doe")
    text = token_saved_message(identity)
    assert "jane.doe" in text
    assert "urn:li:corpuser:jane.doe" in text


def test_token_rejected_message_includes_hint():
    text = token_rejected_message("please reconnect")
    assert "please reconnect" in text


def test_status_message_when_connected():
    identity = DataHubIdentity(username="jane.doe", urn="urn:li:corpuser:jane.doe")
    text = status_message(identity, "2024-01-01T00:00:00+00:00")
    assert "jane.doe" in text
    assert "/datahub-disconnect" in text


def test_status_message_when_not_connected():
    text = status_message(None, None)
    assert "/datahub-connect" in text


def test_disconnected_message_variants():
    assert "deleted" in disconnected_message(had_token=True)
    assert "didn't have" in disconnected_message(had_token=False)


def test_working_on_it_message_is_nonempty():
    assert working_on_it_message()


def test_truncate_for_slack_leaves_short_text_untouched():
    assert truncate_for_slack("short answer") == "short answer"


def test_truncate_for_slack_truncates_long_text():
    long_text = "a" * 5000
    result = truncate_for_slack(long_text, max_chars=100)
    assert len(result) < 5000
    assert "truncated" in result
