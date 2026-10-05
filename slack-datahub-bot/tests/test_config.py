import pytest

from bot.config import ConfigError, Settings

REQUIRED_ENV = {
    "SLACK_BOT_TOKEN": "xoxb-test",
    "SLACK_APP_TOKEN": "xapp-test",
    "SLACK_SIGNING_SECRET": "secret",
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "DATAHUB_GMS_URL": "https://dev-datahub.avenews.io/api/gms",
    "DATAHUB_UI_URL": "https://dev-datahub.avenews.io",
    "ENCRYPTION_KEY": "some-fernet-key",
}


def _set_env(monkeypatch, overrides=None, clear_extra=None):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    for key in clear_extra or []:
        monkeypatch.delenv(key, raising=False)
    for key, value in (overrides or {}).items():
        monkeypatch.setenv(key, value)


def test_loads_required_settings_with_defaults(monkeypatch):
    _set_env(monkeypatch)

    settings = Settings.from_env()

    assert settings.slack_bot_token == "xoxb-test"
    assert settings.datahub_gms_url == "https://dev-datahub.avenews.io/api/gms"
    assert settings.datahub_ui_url == "https://dev-datahub.avenews.io"
    assert settings.claude_model == "claude-sonnet-5-5"
    assert settings.answer_visibility == "private"
    assert settings.max_tool_rounds == 6
    assert settings.tool_result_max_chars == 4000
    assert settings.db_path == "/data/bot.db"
    assert settings.mcp_log_file == "/data/mcp-server.log"


def test_strips_trailing_slash_from_urls(monkeypatch):
    _set_env(
        monkeypatch,
        overrides={
            "DATAHUB_GMS_URL": "https://dev-datahub.avenews.io/api/gms/",
            "DATAHUB_UI_URL": "https://dev-datahub.avenews.io/",
        },
    )

    settings = Settings.from_env()

    assert settings.datahub_gms_url == "https://dev-datahub.avenews.io/api/gms"
    assert settings.datahub_ui_url == "https://dev-datahub.avenews.io"


def test_missing_required_var_raises(monkeypatch):
    _set_env(monkeypatch, clear_extra=["SLACK_BOT_TOKEN"])

    with pytest.raises(ConfigError, match="SLACK_BOT_TOKEN"):
        Settings.from_env()


def test_invalid_answer_visibility_raises(monkeypatch):
    _set_env(monkeypatch, overrides={"ANSWER_VISIBILITY": "public"})

    with pytest.raises(ConfigError, match="ANSWER_VISIBILITY"):
        Settings.from_env()


def test_invalid_int_raises(monkeypatch):
    _set_env(monkeypatch, overrides={"MAX_TOOL_ROUNDS": "not-a-number"})

    with pytest.raises(ConfigError, match="MAX_TOOL_ROUNDS"):
        Settings.from_env()
