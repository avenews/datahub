"""slack_bolt (Socket Mode, async) wiring.

Thin glue only: every handler here just extracts what it needs from the Slack
event/body and delegates to BotHandlers (bot.handlers), which holds the
actual, unit-tested business logic. This module is intentionally not covered
by automated tests since constructing a real AsyncApp talks to Slack's API;
see tests/test_handlers.py for the logic this wires up.
"""

from __future__ import annotations

import logging

from slack_bolt.async_app import AsyncApp

from bot.config import Settings
from bot.formatting import working_on_it_message
from bot.handlers import (
    CONNECT_MODAL_CALLBACK_ID,
    BotHandlers,
    build_connect_modal_view,
    extract_token_from_modal_submission,
)

logger = logging.getLogger("slack_datahub_bot")


def _thread_key(channel: str, thread_ts: str | None, ts: str) -> str:
    return f"{channel}:{thread_ts or ts}"


def build_app(settings: Settings, handlers: BotHandlers) -> AsyncApp:
    app = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )

    @app.command("/datahub-connect")
    async def open_connect_modal(ack, body, client):
        await ack()
        await client.views_open(
            trigger_id=body["trigger_id"],
            view=build_connect_modal_view(),
        )

    @app.view(CONNECT_MODAL_CALLBACK_ID)
    async def handle_connect_view_submission(ack, body, client):
        await ack()
        slack_user_id = body["user"]["id"]
        raw_token = extract_token_from_modal_submission(body["view"]["state"]["values"])
        message = handlers.handle_connect_submission(slack_user_id, raw_token)
        await client.chat_postMessage(channel=slack_user_id, text=message)

    @app.command("/datahub-disconnect")
    async def disconnect(ack, body, respond):
        await ack()
        message = handlers.handle_disconnect(body["user_id"])
        await respond(text=message, response_type="ephemeral")

    @app.command("/datahub-status")
    async def status(ack, body, respond):
        await ack()
        message = handlers.handle_status(body["user_id"])
        await respond(text=message, response_type="ephemeral")

    async def _answer_and_post(client, channel: str, user: str, thread_ts: str, question: str):
        text, connected = await handlers.handle_question(user, _thread_key(channel, thread_ts, thread_ts), question)

        if not connected:
            # Never leak "not connected" or "please reconnect" state to the channel.
            await client.chat_postEphemeral(channel=channel, user=user, text=text)
            return

        if settings.answer_visibility == "private":
            await client.chat_postEphemeral(channel=channel, user=user, text=text, thread_ts=thread_ts)
        else:
            await client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)

    async def _handle_incoming_question(client, channel: str, user: str, thread_ts: str, question: str):
        placeholder = await client.chat_postMessage(
            channel=channel, thread_ts=thread_ts, text=working_on_it_message()
        )
        try:
            await _answer_and_post(client, channel, user, thread_ts, question)
        finally:
            await client.chat_delete(channel=channel, ts=placeholder["ts"])

    @app.event("app_mention")
    async def on_mention(event, client):
        thread_ts = event.get("thread_ts") or event["ts"]
        await _handle_incoming_question(
            client, event["channel"], event["user"], thread_ts, event.get("text", "")
        )

    @app.event("message")
    async def on_dm(event, client):
        if event.get("channel_type") != "im" or event.get("bot_id"):
            return
        thread_ts = event.get("thread_ts") or event["ts"]
        await _handle_incoming_question(
            client, event["channel"], event["user"], thread_ts, event.get("text", "")
        )

    return app
