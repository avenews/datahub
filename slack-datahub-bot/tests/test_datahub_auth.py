import httpx
import pytest
import respx

from bot.datahub_auth import TokenValidationError, validate_token

GMS_URL = "https://dev-datahub.avenews.io/api/gms"
GRAPHQL_URL = f"{GMS_URL}/api/graphql"


@respx.mock
def test_validate_token_returns_identity_on_success():
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"me": {"corpUser": {"urn": "urn:li:corpuser:jane.doe", "username": "jane.doe"}}}},
        )
    )

    identity = validate_token(GMS_URL, "good-token")

    assert identity.username == "jane.doe"
    assert identity.urn == "urn:li:corpuser:jane.doe"


@respx.mock
def test_validate_token_sends_bearer_header():
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"me": {"corpUser": {"urn": "urn:li:corpuser:jane.doe", "username": "jane.doe"}}}},
        )
    )

    validate_token(GMS_URL, "good-token")

    assert route.calls.last.request.headers["Authorization"] == "Bearer good-token"


@respx.mock
def test_validate_token_401_raises_with_reconnect_hint():
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(401))

    with pytest.raises(TokenValidationError) as exc_info:
        validate_token(GMS_URL, "expired-token")

    assert "reconnect" in exc_info.value.reconnect_hint.lower() or "expired" in exc_info.value.reconnect_hint.lower()


@respx.mock
def test_validate_token_403_raises():
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(403))

    with pytest.raises(TokenValidationError):
        validate_token(GMS_URL, "bad-token")


@respx.mock
def test_validate_token_missing_corp_user_raises():
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(200, json={"data": {"me": None}}))

    with pytest.raises(TokenValidationError):
        validate_token(GMS_URL, "weird-token")


@respx.mock
def test_validate_token_graphql_errors_raises():
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "boom"}]})
    )

    with pytest.raises(TokenValidationError):
        validate_token(GMS_URL, "any-token")


@respx.mock
def test_validate_token_network_error_raises():
    respx.post(GRAPHQL_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    with pytest.raises(TokenValidationError):
        validate_token(GMS_URL, "any-token")
