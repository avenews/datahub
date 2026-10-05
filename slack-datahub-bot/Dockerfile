FROM python:3.12-slim

RUN groupadd --gid 10001 botgroup \
    && useradd --uid 10001 --gid botgroup --create-home --shell /usr/sbin/nologin botuser

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data && chown -R botuser:botgroup /data /app
VOLUME ["/data"]

USER botuser

# No EXPOSE: Socket Mode is outbound-only, and the DataHub MCP server is
# only ever spawned as a short-lived per-question subprocess (see
# bot/mcp_client.py) -- nothing in this container listens on any port.

ENTRYPOINT ["./entrypoint.sh"]
