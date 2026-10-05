from types import SimpleNamespace

import pytest

from bot.claude_orchestrator import ClaudeDataHubAnswerer


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, arguments, tool_id="tool-1"):
    return SimpleNamespace(type="tool_use", name=name, input=arguments, id=tool_id)


def message(stop_reason, content):
    return SimpleNamespace(stop_reason=stop_reason, content=content)


class FakeMessagesEndpoint:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = FakeMessagesEndpoint(responses)


class FakeMcpSession:
    def __init__(self, tools=None, call_results=None, raise_on=None):
        self._tools = tools or [
            {"name": "search", "description": "search datahub", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}}
        ]
        self._call_results = call_results or {}
        self._raise_on = raise_on or set()
        self.calls = []

    async def list_tools_as_claude_schema(self):
        return self._tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name in self._raise_on:
            raise RuntimeError("simulated failure")
        return self._call_results.get(name, "{}")


@pytest.mark.asyncio
async def test_answers_directly_when_no_tool_use_needed():
    client = FakeAnthropicClient([message("end_turn", [text_block("*Hello* there")])])
    mcp = FakeMcpSession()
    answerer = ClaudeDataHubAnswerer(
        anthropic_client=client, model="claude-sonnet-5-5", datahub_ui_url="https://dh.example",
        mcp_tool_error_type=RuntimeError,
    )

    result = await answerer.answer(mcp, history=[], question="hi")

    assert result.text == "*Hello* there"
    assert result.tool_rounds_used == 0
    assert result.hit_round_cap is False
    assert mcp.calls == []


@pytest.mark.asyncio
async def test_performs_one_tool_round_then_answers():
    client = FakeAnthropicClient(
        [
            message("tool_use", [tool_use_block("search", {"query": "revenue"})]),
            message("end_turn", [text_block("Found it: <https://dh.example/dataset/x|revenue>")]),
        ]
    )
    mcp = FakeMcpSession(call_results={"search": '{"urn": "urn:li:dataset:x"}'})
    answerer = ClaudeDataHubAnswerer(
        anthropic_client=client, model="claude-sonnet-5-5", datahub_ui_url="https://dh.example",
        mcp_tool_error_type=RuntimeError,
    )

    result = await answerer.answer(mcp, history=[], question="find revenue dataset")

    assert "revenue" in result.text
    assert result.tool_rounds_used == 1
    assert mcp.calls == [("search", {"query": "revenue"})]

    second_call_messages = client.messages.calls[1]["messages"]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["role"] == "user"
    assert tool_result_message["content"][0]["type"] == "tool_result"
    assert tool_result_message["content"][0]["tool_use_id"] == "tool-1"


@pytest.mark.asyncio
async def test_tool_error_is_reported_back_to_claude_not_raised():
    client = FakeAnthropicClient(
        [
            message("tool_use", [tool_use_block("search", {"query": "x"})]),
            message("end_turn", [text_block("Sorry, I could not find that.")]),
        ]
    )
    mcp = FakeMcpSession(raise_on={"search"})
    answerer = ClaudeDataHubAnswerer(
        anthropic_client=client, model="claude-sonnet-5-5", datahub_ui_url="https://dh.example",
        mcp_tool_error_type=RuntimeError,
    )

    result = await answerer.answer(mcp, history=[], question="find x")

    tool_result_content = client.messages.calls[1]["messages"][-1]["content"][0]["content"]
    assert "Tool call failed" in tool_result_content
    assert result.text == "Sorry, I could not find that."


@pytest.mark.asyncio
async def test_large_tool_result_is_truncated():
    client = FakeAnthropicClient(
        [
            message("tool_use", [tool_use_block("search", {"query": "x"})]),
            message("end_turn", [text_block("done")]),
        ]
    )
    mcp = FakeMcpSession(call_results={"search": "A" * 10_000})
    answerer = ClaudeDataHubAnswerer(
        anthropic_client=client, model="claude-sonnet-5-5", datahub_ui_url="https://dh.example",
        tool_result_max_chars=100, mcp_tool_error_type=RuntimeError,
    )

    await answerer.answer(mcp, history=[], question="find x")

    tool_result_content = client.messages.calls[1]["messages"][-1]["content"][0]["content"]
    assert len(tool_result_content) < 200
    assert "truncated" in tool_result_content


@pytest.mark.asyncio
async def test_round_cap_forces_final_no_tool_answer():
    responses = [message("tool_use", [tool_use_block("search", {"query": "x"}, tool_id=f"t{i}")]) for i in range(3)]
    responses.append(message("end_turn", [text_block("Here is what I found so far.")]))
    client = FakeAnthropicClient(responses)
    mcp = FakeMcpSession(call_results={"search": "some result"})
    answerer = ClaudeDataHubAnswerer(
        anthropic_client=client, model="claude-sonnet-5-5", datahub_ui_url="https://dh.example",
        max_tool_rounds=3, mcp_tool_error_type=RuntimeError,
    )

    result = await answerer.answer(mcp, history=[], question="find x")

    assert result.hit_round_cap is True
    assert result.tool_rounds_used == 3
    assert result.text == "Here is what I found so far."
    final_call_kwargs = client.messages.calls[-1]
    assert final_call_kwargs["tool_choice"] == {"type": "none"}
