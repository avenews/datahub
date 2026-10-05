# DataHub Catalog Slack Bot

A Slack bot that answers questions about your DataHub data catalog using
Claude, with **every answer generated under the asking person's own DataHub
permissions** -- never a shared or service-account token.

## How it enforces per-person permissions

- Each person links their own DataHub personal access token once, via a
  private Slack modal (`/datahub-connect`). Tokens are never posted in a
  channel.
- Tokens are stored encrypted at rest (Fernet, key from `ENCRYPTION_KEY`) in a
  local SQLite file.
- When answering a question, the bot spawns a fresh, short-lived
  `mcp-server-datahub` (the official DataHub MCP server) **stdio subprocess**
  with only that person's token in its environment, then tears it down. A new
  subprocess is created per question, so tokens are never shared or reused
  across people, and DataHub's own permission checks and audit log see the
  real person.
- If a token is invalid, expired, or revoked, the bot tells the person
  clearly how to reconnect and never falls back to any other credential.

This is why there's no separately-hosted MCP server and no "shared" DataHub
identity anywhere in this design.

## Hosting

- One container. Slack **Socket Mode** (outbound WebSocket only): no public
  URL, no inbound ports, no domain, no reverse proxy.
- The DataHub MCP server is not a standing process -- see above.

## Requirements

- Docker and Docker Compose (tested with Docker 29 / Compose v2 on
  Ubuntu/WSL).
- A Slack workspace where you can install apps.
- An Anthropic API key.
- A DataHub instance with `METADATA_SERVICE_AUTH_ENABLED=true`, so DataHub
  personal access tokens map to real actors and permissions.

## 1. Create the Slack app

1. Go to <https://api.slack.com/apps> -> **Create New App** -> **From an app
   manifest**.
2. Pick your workspace, then paste the contents of
   [`slack-app-manifest.yml`](slack-app-manifest.yml).
3. After creation:
   - **Basic Information** -> **App-Level Tokens** -> generate a token with
     the `connections:write` scope. This is `SLACK_APP_TOKEN` (`xapp-...`).
   - **Basic Information** -> copy the **Signing Secret** ->
     `SLACK_SIGNING_SECRET`.
   - **OAuth & Permissions** -> **Install to Workspace** -> copy the **Bot
     User OAuth Token** -> `SLACK_BOT_TOKEN` (`xoxb-...`).
4. Invite the bot to any channel you want it to answer in
   (`/invite @DataHub Catalog Bot`), or just DM it directly.

The manifest requests only: `app_mentions:read`, `chat:write`, `commands`,
`im:history`, `im:read`, plus the three slash commands
(`/datahub-connect`, `/datahub-disconnect`, `/datahub-status`) and Socket
Mode + interactivity (for the token-entry modal).

## 2. Configure

```bash
cp .env.example .env
```

Fill in every value in `.env` yourself -- see the comments in that file for
what each one means and where to find it. In particular:

- `DATAHUB_GMS_URL` should be the GMS URL as reachable from this container
  (in this deployment, the frontend-proxied path, e.g.
  `https://dev-datahub.avenews.io/api/gms`).
- Do **not** set a `DATAHUB_GMS_TOKEN` anywhere -- this bot intentionally
  never has one.
- Generate `ENCRYPTION_KEY` with `openssl rand -hex 32`.

## 3. Run it

```bash
docker compose up --build -d
docker compose logs -f
```

Data (the SQLite token store and the MCP subprocess's log file) persists in
the `bot-data` Docker volume across restarts.

## 4. Use it

- **Connect:** run `/datahub-connect` in Slack, paste your DataHub personal
  access token into the modal. Create one in DataHub under **Settings** ->
  **Access Tokens** -> **Generate new token** -> **Personal Token**.
- **Ask questions:** DM the bot, or `@mention` it in any channel it's in.
  Follow-up questions in the same thread keep context.
- **Check status:** `/datahub-status`.
- **Disconnect:** `/datahub-disconnect` (deletes your stored token).

### Where answers are posted

Controlled by `ANSWER_VISIBILITY` in `.env`:

- `private` (**default**): answers to `@mention`s in a channel are posted as
  an ephemeral message visible only to the person who asked. DMs always
  behave normally (only the asker sees them anyway).
- `thread`: answers are posted in the channel thread, visible to everyone
  there.

Default is `private` because different people can have different DataHub
permissions -- a public thread reply could show one person's answer
(including which datasets/owners exist) to others who aren't allowed to see
that in DataHub itself.

## Claude behavior

Claude is instructed to answer only from what the DataHub MCP tools actually
return -- never to invent datasets, owners, or lineage -- and to say plainly
when a result might be incomplete because of the asker's own DataHub
permissions. Tool-use is capped at `MAX_TOOL_ROUNDS` per question, and each
tool result is truncated to `TOOL_RESULT_MAX_CHARS` before being sent to
Claude, to bound cost and latency. The model ID comes from `CLAUDE_MODEL`;
check [Anthropic's model docs](https://platform.claude.com/docs/en/about-claude/models/overview)
periodically, since model names and retirement dates change over time.

## Development

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/pytest -q
```

All tests run offline: no real Slack, DataHub, or Claude connection is
needed. `tests/fixtures/fake_mcp_server.py` is a tiny fake DataHub MCP server
run as a real stdio subprocess, used to test the actual per-question
subprocess-spawning code path.

Project layout:

```
src/bot/
  config.py             # env var loading/validation
  crypto.py              # Fernet encryption for stored tokens
  storage.py             # SQLite: one row per Slack user's linked token
  datahub_auth.py        # validates a DataHub token via GraphQL, returns identity
  mcp_client.py           # spawns mcp-server-datahub per question, per user token
  claude_orchestrator.py  # Claude tool-use loop against the MCP session
  conversation.py         # in-memory per-thread follow-up context
  formatting.py           # Slack mrkdwn messages (connect/status/errors)
  handlers.py             # business logic, unit tested with fakes
  slack_app.py            # slack_bolt (Socket Mode, async) wiring -- thin glue
  main.py                 # entrypoint, wires everything from env
```

## Troubleshooting

- **Bot doesn't respond to `@mention`s:** confirm it's actually invited to
  the channel, and that Socket Mode is connected (check container logs for
  `Starting Slack Socket Mode connection`).
- **"Missing required environment variable" on startup:** an entry in `.env`
  is empty; the error names exactly which one.
- **A user's questions always say "you haven't connected":** they need to
  run `/datahub-connect`. If they already have, check `/datahub-status`.
- **"Your DataHub token looks expired or revoked":** the token was deleted or
  expired in DataHub itself. Generate a new personal access token and run
  `/datahub-connect` again.
- **Answers say a result "may be hidden by your permissions":** this is
  Claude being honest about DataHub's own access control -- the user is
  seeing exactly what their DataHub token is allowed to see, nothing more.
- **MCP server errors in the answer:** check
  `docker compose exec slack-datahub-bot cat /data/mcp-server.log` (or your
  configured `MCP_LOG_FILE`) for the underlying `mcp-server-datahub` output,
  which is kept out of the bot's own stdout logs.
- **Container exits immediately:** check `docker compose logs` -- config
  errors are logged clearly and the process exits non-zero rather than
  running half-configured.
