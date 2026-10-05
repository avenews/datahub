"""Process entrypoint: loads settings, wires dependencies, starts Socket Mode.

Run as: python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging
import sys

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from bot.claude_orchestrator import ClaudeDataHubAnswerer
from bot.config import ConfigError, Settings
from bot.conversation import ThreadContextStore
from bot.crypto import TokenCipher
from bot.datahub_auth import validate_token
from bot.handlers import BotHandlers
from bot.mcp_client import DataHubMcpSession, McpToolError
from bot.slack_app import build_app
from bot.storage import UserStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,  # keep mcp-server-datahub's noisy stderr logging separate
)
logger = logging.getLogger("slack_datahub_bot")


async def async_main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(1) from exc

    store = UserStore(settings.db_path)
    cipher = TokenCipher(settings.encryption_key)
    thread_store = ThreadContextStore()

    from anthropic import AsyncAnthropic

    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    answerer = ClaudeDataHubAnswerer(
        anthropic_client=anthropic_client,
        model=settings.claude_model,
        datahub_ui_url=settings.datahub_ui_url,
        max_tool_rounds=settings.max_tool_rounds,
        tool_result_max_chars=settings.tool_result_max_chars,
        mcp_tool_error_type=McpToolError,
    )

    def mcp_session_factory(token: str) -> DataHubMcpSession:
        return DataHubMcpSession(
            gms_url=settings.datahub_gms_url,
            datahub_token=token,
            mcp_log_file=settings.mcp_log_file,
        )

    handlers = BotHandlers(
        gms_url=settings.datahub_gms_url,
        store=store,
        cipher=cipher,
        thread_store=thread_store,
        validate_token=validate_token,
        mcp_session_factory=mcp_session_factory,
        answerer=answerer,
    )

    app = build_app(settings, handlers)
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    logger.info("Starting Slack Socket Mode connection (answer_visibility=%s)", settings.answer_visibility)
    await handler.start_async()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
