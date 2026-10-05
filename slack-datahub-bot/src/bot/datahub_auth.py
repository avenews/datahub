"""Validates DataHub personal access tokens by calling GMS directly.

This is intentionally independent of the MCP server: validating a token is a
single lightweight GraphQL call, and we want a clear "which DataHub user is
this?" answer at connect time without spinning up an MCP session.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_ME_QUERY = """
query BotValidateToken {
  me {
    corpUser {
      urn
      username
    }
  }
}
"""


class TokenValidationError(Exception):
    """Raised when a token is invalid, expired, revoked, or unreachable.

    `reconnect_hint` is a short, user-facing explanation of what to do next.
    """

    def __init__(self, message: str, reconnect_hint: str):
        super().__init__(message)
        self.reconnect_hint = reconnect_hint


@dataclass(frozen=True)
class DataHubIdentity:
    username: str
    urn: str


RECONNECT_HINT = (
    "Your DataHub token looks expired or revoked. Generate a new one in DataHub "
    "under Settings -> Access Tokens -> Generate new token -> Personal Token, "
    "then run /datahub-connect again."
)


def validate_token(gms_url: str, token: str, *, timeout_seconds: float = 10.0) -> DataHubIdentity:
    url = f"{gms_url}/api/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(
            url,
            headers=headers,
            json={"query": _ME_QUERY},
            timeout=timeout_seconds,
        )
    except httpx.RequestError as exc:
        raise TokenValidationError(
            f"Could not reach DataHub at {gms_url}: {exc}",
            "DataHub could not be reached right now. Please try again shortly, "
            "and contact an admin if this keeps happening.",
        ) from exc

    if response.status_code in (401, 403):
        raise TokenValidationError(
            f"DataHub rejected the token (HTTP {response.status_code})",
            RECONNECT_HINT,
        )
    if response.status_code != 200:
        raise TokenValidationError(
            f"Unexpected response from DataHub (HTTP {response.status_code})",
            "DataHub returned an unexpected error. Please try again, and contact "
            "an admin if this keeps happening.",
        )

    body = response.json()
    errors = body.get("errors")
    if errors:
        raise TokenValidationError(
            f"DataHub GraphQL returned errors: {errors}",
            RECONNECT_HINT,
        )

    corp_user = ((body.get("data") or {}).get("me") or {}).get("corpUser")
    if not corp_user or not corp_user.get("username") or not corp_user.get("urn"):
        raise TokenValidationError(
            "DataHub did not return a resolvable identity for this token",
            RECONNECT_HINT,
        )

    return DataHubIdentity(username=corp_user["username"], urn=corp_user["urn"])
