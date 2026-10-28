"""HTTPS API client tests with a local synthetic session."""

import json

import pytest

from custom_components.powermesh_energy.api import (
    API_KEY_PATTERN,
    PowermeshAuthError,
    PowermeshClient,
    PowermeshConnectionError,
    PowermeshForbiddenError,
    PowermeshOutdatedError,
    PowermeshRateLimitError,
    PowermeshRejectedError,
    UploadResult,
    encode_request,
    parse_buffer_limit,
    validate_connection,
    validate_status,
)
from custom_components.powermesh_energy.const import API_RELEASE, CLIENT_ID, MAX_BODY_BYTES

API_KEY = "pme_" + "a" * 16 + "_" + "b" * 64


class FakeContent:
    def __init__(self, body):
        if isinstance(body, bytes):
            self.body = body
        else:
            self.body = json.dumps(body).encode() if body is not None else b""

    async def read(self, size):
        return self.body[:size]


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status = status
        self.content = FakeContent(body)
        self.headers = {"X-Powermesh-Api-Version": API_RELEASE, **(headers or {})}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def api_client(response):
    session = FakeSession(response)
    return PowermeshClient(session, API_KEY), session


def status_body():
    return {
        "status": "ok",
        "api_version": 2,
        "api_release": API_RELEASE,
        "client": {"minimum": "0.1.0", "latest": "0.1.0"},
        "scopes": ["readings:write"],
        "limits": {
            "requests_per_minute": 60,
            "buffer_limit_readings": 5000,
            "max_readings_per_request": 200,
            "max_body_bytes": MAX_BODY_BYTES,
        },
        "retention_days": 365,
    }


def test_api_key_format_is_strict():
    validate_connection(API_KEY)
    assert API_KEY_PATTERN.fullmatch(API_KEY)
    for invalid in [
        "bte_" + "a" * 16 + "_" + "b" * 64,
        "pme_" + "a" * 15 + "_" + "b" * 64,
        API_KEY.upper(),
    ]:
        with pytest.raises(ValueError):
            validate_connection(invalid)
    validate_connection(API_KEY + " ")


@pytest.mark.parametrize("value", [None, True, False, 0, -1, 1_000_001, "5000", 5.5])
def test_buffer_limit_rejects_missing_or_invalid_values(value):
    with pytest.raises(PowermeshOutdatedError, match="invalid_buffer_limit"):
        parse_buffer_limit({"buffer_limit_readings": value})
    body = status_body()
    body["limits"]["buffer_limit_readings"] = value
    with pytest.raises(PowermeshOutdatedError):
        validate_status(body)


async def test_limits_uses_authenticated_fixed_service():
    body = {"status": "ok", "api_version": 2, "api_release": API_RELEASE, "limits": status_body()["limits"]}
    client, session = api_client(FakeResponse(body=body))
    assert await client.limits() == body
    assert session.calls[0][0] == ("GET", "https://api.powermesh.de/api/v2/limits")
    assert session.calls[0][1]["headers"]["Authorization"].endswith(API_KEY)


async def test_status_uses_fixed_tls_service_and_client_header():
    client, session = api_client(FakeResponse(body=status_body()))
    result = await client.status()
    assert result == status_body()
    args, kwargs = session.calls[0]
    assert args == ("GET", "https://api.powermesh.de/api/v2/status")
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert kwargs["headers"]["X-Powermesh-Client"] == CLIENT_ID == "homeassistant/0.6.0"


async def test_status_rejects_mismatched_api_version_header():
    client, _ = api_client(
        FakeResponse(body=status_body(), headers={"X-Powermesh-Api-Version": "0.0.9"})
    )
    with pytest.raises(PowermeshOutdatedError):
        await client.status()


async def test_upload_requires_exact_storage_acknowledgement():
    reading = {
        "entity_id": "sensor.power",
        "timestamp": "2026-01-01T00:00:00Z",
        "state": 10,
        "unit_of_measurement": "W",
    }
    client, session = api_client(
        FakeResponse(body={"accepted": 1, "duplicates": 0}, headers={"X-RateLimit-Remaining": "7"})
    )
    result = await client.upload([reading])
    assert result == UploadResult(1, 0, 7)
    args, kwargs = session.calls[0]
    assert args == ("POST", "https://api.powermesh.de/api/v2/readings")
    assert kwargs["data"] == encode_request({"readings": [reading]})
    assert kwargs["headers"]["Content-Type"] == "application/json"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"accepted": 1, "duplicates": -1},
        {"accepted": True, "duplicates": 0},
        {"accepted": 0, "duplicates": 0},
    ],
)
async def test_malformed_acknowledgement_is_not_a_storage_confirmation(body):
    client, _ = api_client(FakeResponse(body=body))
    with pytest.raises(PowermeshConnectionError, match="invalid_acknowledgement"):
        await client.upload([{
            "entity_id": "sensor.x",
            "timestamp": "2026-01-01T00:00:00Z",
            "state": 1,
            "unit_of_measurement": "",
        }])


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, {"error": {"code": "invalid_token"}}, PowermeshAuthError),
        (403, {"error": {"code": "consent_required"}}, PowermeshForbiddenError),
        (426, {"error": {"code": "client_outdated"}}, PowermeshOutdatedError),
        (429, {"error": {"code": "rate_limited"}}, PowermeshRateLimitError),
        (422, {"error": {"code": "invalid_readings"}}, PowermeshRejectedError),
        (503, {"error": {"code": "service_unavailable"}}, PowermeshConnectionError),
    ],
)
async def test_http_error_mapping(status, body, error):
    client, _ = api_client(FakeResponse(status=status, body=body, headers={"Retry-After": "12"}))
    with pytest.raises(error):
        await client.status()


async def test_oversized_response_fails_without_parsing():
    client, _ = api_client(FakeResponse(body=b" " * (MAX_BODY_BYTES + 1)))
    with pytest.raises(PowermeshConnectionError, match="invalid_response"):
        await client.status()


def test_request_encoder_rejects_nan_and_oversized_body():
    with pytest.raises(PowermeshRejectedError):
        encode_request({"readings": [{"state": float("nan")}]})
    with pytest.raises(PowermeshRejectedError):
        encode_request({"large": "x" * MAX_BODY_BYTES})


async def test_upload_rejects_more_than_200_readings():
    client, session = api_client(FakeResponse(body={"accepted": 200, "duplicates": 0}))
    reading = {
        "entity_id": "sensor.power",
        "timestamp": "2026-01-01T00:00:00Z",
        "state": 10,
        "unit_of_measurement": "W",
    }
    with pytest.raises(PowermeshRejectedError):
        await client.upload([reading] * 201)
    assert session.calls == []
