"""Pure(ish) business logic for the bot's Slack-facing behaviors.

Kept separate from slack_bolt registration (see slack_app.py) so it can be
unit tested with fakes instead of a real Slack/DataHub/Claude connection.
Dependencies are injected as callables/objects so tests can substitute fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from bot.claude_orchestrator import AnswerResult
from bot.conversation import ThreadContextStore
from bot.crypto import DecryptionError, TokenCipher
from bot.datahub_auth import DataHubIdentity, TokenValidationError
from bot.formatting import (
    disconnected_message,
    not_connected_message,
    status_message,
    token_rejected_message,
    token_saved_message,
    truncate_for_slack,
)
from bot.storage import UserStore

CONNECT_MODAL_CALLBACK_ID = "datahub_connect_modal"
CONNECT_MODAL_TOKEN_BLOCK_ID = "datahub_token_block"
CONNECT_MODAL_TOKEN_ACTION_ID = "datahub_token_input"


def build_connect_modal_view() -> dict[str, Any]:
    """Slack modal (private, never a channel message) for pasting a token."""
    return {
        "type": "modal",
        "callback_id": CONNECT_MODAL_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Connect DataHub"},
        "submit": {"type": "plain_text", "text": "Connect"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "Paste your DataHub *personal access token*. Create one in DataHub "
                        "under Settings -> Access Tokens -> Generate new token -> Personal Token."
                    ),
                },
            },
            {
                "type": "input",
                "block_id": CONNECT_MODAL_TOKEN_BLOCK_ID,
                "label": {"type": "plain_text", "text": "DataHub personal access token"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": CONNECT_MODAL_TOKEN_ACTION_ID,
                },
            },
        ],
    }


def extract_token_from_modal_submission(view_state_values: dict[str, Any]) -> str:
    return (
        view_state_values.get(CONNECT_MODAL_TOKEN_BLOCK_ID, {})
        .get(CONNECT_MODAL_TOKEN_ACTION_ID, {})
        .get("value", "")
        .strip()
    )


class TokenValidator(Protocol):
    def __call__(self, gms_url: str, token: str) -> DataHubIdentity: ...


class McpSessionFactory(Protocol):
    def __call__(self, token: str) -> Any: ...  # async context manager


class Answerer(Protocol):
    async def answer(
        self, mcp_session: Any, history: list[dict[str, Any]], question: str
    ) -> AnswerResult: ...


@dataclass
class BotHandlers:
    gms_url: str
    store: UserStore
    cipher: TokenCipher
    thread_store: ThreadContextStore
    validate_token: TokenValidator
    mcp_session_factory: McpSessionFactory
    answerer: Answerer

    def handle_connect_submission(self, slack_user_id: str, raw_token: str) -> str:
        if not raw_token:
            return token_rejected_message("No token was provided.")
        try:
            identity = self.validate_token(self.gms_url, raw_token)
        except TokenValidationError as exc:
            return token_rejected_message(exc.reconnect_hint)

        encrypted = self.cipher.encrypt(raw_token)
        self.store.save(slack_user_id, encrypted, identity.username, identity.urn)
        return token_saved_message(identity)

    def handle_disconnect(self, slack_user_id: str) -> str:
        had_token = self.store.delete(slack_user_id)
        return disconnected_message(had_token)

    def handle_status(self, slack_user_id: str) -> str:
        user = self.store.get(slack_user_id)
        if user is None:
            return status_message(None, None)
        identity = DataHubIdentity(username=user.datahub_username, urn=user.datahub_urn)
        return status_message(identity, user.connected_at)

    async def handle_question(
        self, slack_user_id: str, thread_key: str, question: str
    ) -> tuple[str, bool]:
        """Returns (message_text, connected). connected=False means the caller
        should treat this as a private nudge to connect, not a real answer."""
        user = self.store.get(slack_user_id)
        if user is None:
            return not_connected_message(), False

        try:
            token = self.cipher.decrypt(user.encrypted_token)
        except DecryptionError:
            return token_rejected_message(
                "Your saved token could not be decrypted. Please run /datahub-connect again."
            ), False

        try:
            self.validate_token(self.gms_url, token)
        except TokenValidationError as exc:
            return token_rejected_message(exc.reconnect_hint), False

        history = self.thread_store.get_history(thread_key)
        async with self.mcp_session_factory(token) as session:
            result = await self.answerer.answer(session, history, question)

        self.thread_store.append_turn(thread_key, question, result.text)

        text = truncate_for_slack(result.text)
        if result.hit_round_cap:
            text += (
                "\n\n_I hit my limit of tool calls for this question -- the answer above "
                "may be incomplete. Try asking a more specific follow-up._"
            )
        return text, True
