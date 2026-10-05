"""SQLite-backed storage for per-Slack-user encrypted DataHub tokens.

Only one table: each Slack user has at most one linked DataHub token.
Tokens are stored encrypted (see crypto.py); this module never sees plaintext
tokens except when handing them back to callers who already hold the cipher.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class StoredUser:
    slack_user_id: str
    encrypted_token: bytes
    datahub_username: str
    datahub_urn: str
    connected_at: str


class UserStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    slack_user_id TEXT PRIMARY KEY,
                    encrypted_token BLOB NOT NULL,
                    datahub_username TEXT NOT NULL,
                    datahub_urn TEXT NOT NULL,
                    connected_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def save(
        self,
        slack_user_id: str,
        encrypted_token: bytes,
        datahub_username: str,
        datahub_urn: str,
    ) -> None:
        connected_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO users (slack_user_id, encrypted_token, datahub_username, datahub_urn, connected_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slack_user_id) DO UPDATE SET
                    encrypted_token = excluded.encrypted_token,
                    datahub_username = excluded.datahub_username,
                    datahub_urn = excluded.datahub_urn,
                    connected_at = excluded.connected_at
                """,
                (slack_user_id, encrypted_token, datahub_username, datahub_urn, connected_at),
            )
            conn.commit()

    def get(self, slack_user_id: str) -> StoredUser | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT slack_user_id, encrypted_token, datahub_username, datahub_urn, connected_at "
                "FROM users WHERE slack_user_id = ?",
                (slack_user_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredUser(*row)

    def delete(self, slack_user_id: str) -> bool:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM users WHERE slack_user_id = ?", (slack_user_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
