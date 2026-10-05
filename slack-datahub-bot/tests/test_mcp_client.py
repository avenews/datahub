import sys
from pathlib import Path

import pytest

from bot.mcp_client import DataHubMcpSession, McpToolError

FAKE_SERVER_SCRIPT = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")


def make_session(token: str) -> DataHubMcpSession:
    return DataHubMcpSession(
        gms_url="https://dev-datahub.avenews.io/api/gms",
        datahub_token=token,
        command=sys.executable,
        args=[FAKE_SERVER_SCRIPT],
    )


@pytest.mark.asyncio
async def test_list_tools_returns_claude_compatible_schema():
    async with make_session("user-a-token") as session:
        tools = await session.list_tools_as_claude_schema()

    names = {tool["name"] for tool in tools}
    assert {"search", "whoami", "boom"} <= names
    search_tool = next(t for t in tools if t["name"] == "search")
    assert "input_schema" in search_tool
    assert search_tool["input_schema"]["properties"]["query"]


@pytest.mark.asyncio
async def test_call_tool_returns_text_result():
    async with make_session("user-a-token") as session:
        result = await session.call_tool("search", {"query": "revenue"})

    assert "revenue" in result
    assert "urn:li:dataset" in result


@pytest.mark.asyncio
async def test_call_tool_uses_this_users_own_token():
    async with make_session("user-specific-token-123") as session:
        result = await session.call_tool("whoami", {})

    assert "user-specific-token-123" in result


@pytest.mark.asyncio
async def test_different_sessions_carry_different_tokens():
    async with make_session("token-for-alice") as session:
        alice_result = await session.call_tool("whoami", {})
    async with make_session("token-for-bob") as session:
        bob_result = await session.call_tool("whoami", {})

    assert "token-for-alice" in alice_result
    assert "token-for-bob" in bob_result
    assert alice_result != bob_result


@pytest.mark.asyncio
async def test_call_tool_failure_raises_mcp_tool_error():
    async with make_session("user-a-token") as session:
        with pytest.raises(McpToolError):
            await session.call_tool("boom", {})
