#!/usr/bin/env python3
"""A minimal in-process fake of mcp-server-datahub, run as a stdio subprocess.

Used only by tests to exercise DataHubMcpSession's real subprocess-spawning
code path without any real DataHub/network dependency. `whoami` reads the
token from its own process environment (DATAHUB_GMS_TOKEN) -- exactly how the
real per-question subprocess isolation is meant to work.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

fake_datahub_mcp = FastMCP("fake-datahub")


@fake_datahub_mcp.tool
def search(query: str) -> dict:
    """Fake search tool: echoes the query back with a canned result."""
    return {"query": query, "results": [{"urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.t,PROD)"}]}


@fake_datahub_mcp.tool
def whoami() -> dict:
    """Returns the DataHub token this subprocess was started with."""
    return {"token": os.environ.get("DATAHUB_GMS_TOKEN", "")}


@fake_datahub_mcp.tool
def boom() -> dict:
    """Always fails, to exercise the error path."""
    raise RuntimeError("simulated tool failure")


if __name__ == "__main__":
    fake_datahub_mcp.run(transport="stdio", show_banner=False)

