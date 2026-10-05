#!/usr/bin/env bash
# The DataHub MCP server is not run as a standing process: it's spawned
# fresh, per Slack question, by the bot itself (see bot/mcp_client.py) with
# that specific user's token in its own subprocess environment. This script
# just makes sure /data exists and then execs the bot as the container's main
# process.
set -euo pipefail

mkdir -p /data
exec python -m bot.main
