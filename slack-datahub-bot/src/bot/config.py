"""Environment-driven configuration for the bot.

All values are read once at process start. Nothing here should be logged
verbatim since some fields (Slack/Anthropic tokens, encryption key) are secrets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _optional(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def _optional_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc


@dataclass(frozen=True)
class Settings:
    slack_bot_token: str
    slack_app_token: str
    slack_signing_secret: str

    anthropic_api_key: str
    claude_model: str

    datahub_gms_url: str
    datahub_ui_url: str

    encryption_key: str

    db_path: str
    mcp_log_file: str

    answer_visibility: str  # "private" or "thread"
    max_tool_rounds: int
    tool_result_max_chars: int

    @staticmethod
    def from_env() -> "Settings":
        answer_visibility = _optional("ANSWER_VISIBILITY", "private").lower()
        if answer_visibility not in ("private", "thread"):
            raise ConfigError(
                f"ANSWER_VISIBILITY must be 'private' or 'thread', got {answer_visibility!r}"
            )

        return Settings(
            slack_bot_token=_require("SLACK_BOT_TOKEN"),
            slack_app_token=_require("SLACK_APP_TOKEN"),
            slack_signing_secret=_require("SLACK_SIGNING_SECRET"),
            anthropic_api_key=_require("ANTHROPIC_API_KEY"),
            claude_model=_optional("CLAUDE_MODEL", "claude-sonnet-5-5"),
            datahub_gms_url=_require("DATAHUB_GMS_URL").rstrip("/"),
            datahub_ui_url=_require("DATAHUB_UI_URL").rstrip("/"),
            encryption_key=_require("ENCRYPTION_KEY"),
            db_path=_optional("DB_PATH", "/data/bot.db"),
            mcp_log_file=_optional("MCP_LOG_FILE", "/data/mcp-server.log"),
            answer_visibility=answer_visibility,
            max_tool_rounds=_optional_int("MAX_TOOL_ROUNDS", 6),
            tool_result_max_chars=_optional_int("TOOL_RESULT_MAX_CHARS", 4000),
        )
