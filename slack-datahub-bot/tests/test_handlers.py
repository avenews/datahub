from dataclasses import dataclass

import pytest

from bot.claude_orchestrator import AnswerResult
from bot.conversation import ThreadContextStore
from bot.crypto import TokenCipher
from bot.datahub_auth import DataHubIdentity, TokenValidationError
from bot.handlers import (
    BotHandlers,
    build_connect_modal_view,
    extract_token_from_modal_submission,
)
from bot.storage import UserStore

GMS_URL = "https://dev-datahub.avenews.io/api/gms"


class FakeMcpSessionCtx:
    def __init__(self, token):
        self.token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeAnswerer:
    def __init__(self, result: AnswerResult):
        self._result = result
        self.received = None

    async def answer(self, mcp_session, history, question):
        self.received = (mcp_session.token, history, question)
        return self._result


@dataclass
class FakeValidator:
    identity: DataHubIdentity | None = None
    error: TokenValidationError | None = None
    calls: list = None

    def __post_init__(self):
        self.calls = []

    def __call__(self, gms_url, token):
        self.calls.append((gms_url, token))
        if self.error is not None:
            raise self.error
        return self.identity


def make_handlers(tmp_path, validator=None, answerer=None):
    store = UserStore(str(tmp_path / "bot.db"))
    cipher = TokenCipher("test-key")
    thread_store = ThreadContextStore()
    validator = validator or FakeValidator(identity=DataHubIdentity("jane.doe", "urn:li:corpuser:jane.doe"))
    answerer = answerer or FakeAnswerer(AnswerResult(text="answer", tool_rounds_used=1, hit_round_cap=False))
    handlers = BotHandlers(
        gms_url=GMS_URL,
        store=store,
        cipher=cipher,
        thread_store=thread_store,
        validate_token=validator,
        mcp_session_factory=FakeMcpSessionCtx,
        answerer=answerer,
    )
    return handlers, store, cipher, thread_store, validator, answerer


def test_connect_modal_view_has_private_input_not_a_message():
    view = build_connect_modal_view()
    assert view["type"] == "modal"
    assert any(block["type"] == "input" for block in view["blocks"])


def test_extract_token_from_modal_submission():
    state = {"datahub_token_block": {"datahub_token_input": {"value": "  my-token  "}}}
    assert extract_token_from_modal_submission(state) == "my-token"


def test_connect_submission_saves_token_on_valid_response(tmp_path):
    handlers, store, cipher, *_ = make_handlers(tmp_path)

    message = handlers.handle_connect_submission("U1", "good-token")

    assert "jane.doe" in message
    stored = store.get("U1")
    assert stored is not None
    assert cipher.decrypt(stored.encrypted_token) == "good-token"


def test_connect_submission_rejects_invalid_token(tmp_path):
    validator = FakeValidator(error=TokenValidationError("bad", "please reconnect"))
    handlers, store, *_ = make_handlers(tmp_path, validator=validator)

    message = handlers.handle_connect_submission("U1", "bad-token")

    assert "please reconnect" in message
    assert store.get("U1") is None


def test_connect_submission_rejects_empty_token(tmp_path):
    handlers, store, *_ = make_handlers(tmp_path)

    message = handlers.handle_connect_submission("U1", "")

    assert "No token" in message
    assert store.get("U1") is None


def test_disconnect_removes_token(tmp_path):
    handlers, store, *_ = make_handlers(tmp_path)
    handlers.handle_connect_submission("U1", "good-token")

    message = handlers.handle_disconnect("U1")

    assert "deleted" in message
    assert store.get("U1") is None


def test_disconnect_when_not_connected(tmp_path):
    handlers, *_ = make_handlers(tmp_path)

    message = handlers.handle_disconnect("U1")

    assert "didn't have" in message


def test_status_when_connected_and_not_connected(tmp_path):
    handlers, *_ = make_handlers(tmp_path)
    assert "/datahub-connect" in handlers.handle_status("U1")

    handlers.handle_connect_submission("U1", "good-token")
    assert "jane.doe" in handlers.handle_status("U1")


@pytest.mark.asyncio
async def test_question_from_unconnected_user_gets_connect_prompt(tmp_path):
    handlers, *_ = make_handlers(tmp_path)

    text, connected = await handlers.handle_question("U1", "thread-1", "what is dataset x?")

    assert connected is False
    assert "/datahub-connect" in text


@pytest.mark.asyncio
async def test_question_from_connected_user_calls_answerer_with_own_token(tmp_path):
    answerer = FakeAnswerer(AnswerResult(text="Here's the answer", tool_rounds_used=1, hit_round_cap=False))
    handlers, *_ , answerer = make_handlers(tmp_path, answerer=answerer)
    handlers.handle_connect_submission("U1", "good-token")

    text, connected = await handlers.handle_question("U1", "thread-1", "what is dataset x?")

    assert connected is True
    assert text == "Here's the answer"
    assert answerer.received[0] == "good-token"
    assert answerer.received[2] == "what is dataset x?"


@pytest.mark.asyncio
async def test_question_appends_to_thread_history(tmp_path):
    handlers, *_, thread_store, _validator, _answerer = make_handlers(tmp_path)
    handlers.handle_connect_submission("U1", "good-token")

    await handlers.handle_question("U1", "thread-1", "first question")

    history = thread_store.get_history("thread-1")
    assert history[0]["content"] == "first question"


@pytest.mark.asyncio
async def test_question_with_expired_token_tells_user_to_reconnect(tmp_path):
    validator = FakeValidator(identity=DataHubIdentity("jane.doe", "urn:li:corpuser:jane.doe"))
    handlers, *_ = make_handlers(tmp_path, validator=validator)
    handlers.handle_connect_submission("U1", "good-token")

    validator.error = TokenValidationError("expired", "Your token looks expired, reconnect please")
    text, connected = await handlers.handle_question("U1", "thread-1", "q")

    assert connected is False
    assert "reconnect" in text.lower()


@pytest.mark.asyncio
async def test_question_hitting_round_cap_appends_warning(tmp_path):
    answerer = FakeAnswerer(AnswerResult(text="partial answer", tool_rounds_used=6, hit_round_cap=True))
    handlers, *_ = make_handlers(tmp_path, answerer=answerer)
    handlers.handle_connect_submission("U1", "good-token")

    text, connected = await handlers.handle_question("U1", "thread-1", "q")

    assert connected is True
    assert "partial answer" in text
    assert "limit of tool calls" in text
