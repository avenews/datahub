"""Runs mcp-server-datahub as a short-lived stdio subprocess, one per Slack
question, with that specific user's DataHub token injected only into that
subprocess's own environment.

This -- not a shared, long-running HTTP MCP server -- is how per-user DataHub
identity is enforced end to end: each subprocess only ever has one user's
token, so DataHub's permission checks and audit log reflect the real asker,
and tokens never leak between users. It also means no separately hosted MCP
server process is needed; it's spawned and torn down in-process by the bot.

We use the low-level `mcp` SDK (not fastmcp's Client) specifically so we can
redirect the subprocess's very chatty stderr logging away from the bot's own
stdout/stderr logs, per project requirements.
"""

from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpToolError(Exception):
    """Raised when a DataHub MCP tool call fails."""


def _extract_text(content: list[Any]) -> str:
    parts = [block.text for block in content if hasattr(block, "text")]
    return "\n".join(parts)


class DataHubMcpSession:
    """One short-lived MCP stdio session scoped to a single DataHub user's token."""

    def __init__(
        self,
        gms_url: str,
        datahub_token: str,
        mcp_log_file: str = os.devnull,
        command: str = "mcp-server-datahub",
        args: list[str] | None = None,
    ):
        self._gms_url = gms_url
        self._datahub_token = datahub_token
        self._mcp_log_file = mcp_log_file
        self._command = command
        self._args = args or []
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "DataHubMcpSession":
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        # Only this session's subprocess env carries this user's token --
        # never a shared/service-account credential.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "DATAHUB_GMS_URL": self._gms_url,
            "DATAHUB_GMS_TOKEN": self._datahub_token,
        }
        server_params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=env,
        )

        errlog = self._stack.enter_context(open(self._mcp_log_file, "a"))
        read_stream, write_stream = await self._stack.enter_async_context(
            stdio_client(server_params, errlog=errlog)
        )
        self._session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        assert self._stack is not None
        await self._stack.__aexit__(*exc_info)
        self._session = None
        self._stack = None

    async def list_tools_as_claude_schema(self) -> list[dict[str, Any]]:
        assert self._session is not None
        result = await self._session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        assert self._session is not None
        result = await self._session.call_tool(name, arguments)

        if result.isError:
            raise McpToolError(_extract_text(result.content) or f"Tool {name} failed")

        text = _extract_text(result.content)
        if text:
            return text
        if result.structuredContent:
            return json.dumps(result.structuredContent)
        return ""
