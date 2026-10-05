"""Static Slack mrkdwn message builders.

Claude is responsible for formatting/links inside its own answers (see the
system prompt in claude_orchestrator.py). This module only covers the bot's
own fixed messages (connect/disconnect/status/errors) so they stay consistent
and are unit-testable without hitting Slack or Claude.
"""

from __future__ import annotations

from bot.datahub_auth import DataHubIdentity

SLACK_MESSAGE_MAX_CHARS = 3500  # keep well under Slack's ~40k block text limit


def not_connected_message() -> str:
    return (
        ":wave: Hey! I'm the Avenews Data Buddy. Before I can dig through the catalog for you, "
        "I need to link your DataHub account so I only show what *you* are allowed to see.\n\n"
        "Quick setup (about a minute):\n"
        "1. Open DataHub -> *Settings* -> *Access Tokens* -> *Generate new token* -> "
        "*Personal Token*\n"
        "2. Copy the token\n"
        "3. Run `/datahub-connect` here in Slack and paste it into the form\n\n"
        "Your token is stored encrypted and only used to answer *your* questions, "
        "under your own Avenews DataHub permissions."
    )


def token_saved_message(identity: DataHubIdentity) -> str:
    return (
        f":tada: You're in, *{identity.username}*! (`{identity.urn}`)\n"
        "Ask me anything about Avenews data, here in a DM or by @mentioning me in a channel. "
        "Try: _\"Where do we keep subscriber data?\"_"
    )


def token_rejected_message(reconnect_hint: str) -> str:
    return f":warning: {reconnect_hint}"


def status_message(identity: DataHubIdentity | None, connected_at: str | None) -> str:
    if identity is None:
        return ":closed_lock_with_key: We're not connected yet. Run `/datahub-connect` to link your DataHub account."
    when = f" since {connected_at}" if connected_at else ""
    return (
        f":white_check_mark: All set, *{identity.username}*! "
        f"(`{identity.urn}`) connected{when}. Run `/datahub-disconnect` any time to remove your token."
    )


def disconnected_message(had_token: bool) -> str:
    if had_token:
        return ":wastebasket: Done. Your DataHub token has been deleted. Come back any time with `/datahub-connect`."
    return "Nothing to remove: you didn't have a DataHub token connected."


def working_on_it_message() -> str:
    return ":mag: On it! Digging through the Avenews catalog, back in a few seconds..."


def truncate_for_slack(text: str, max_chars: int = SLACK_MESSAGE_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n_(answer truncated)_"
