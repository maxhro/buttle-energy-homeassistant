"""HTTPS client for the powermesh.de readings API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .const import (
    API_MAJOR,
    CLIENT_ID,
    DEFAULT_URL,
    MAX_BODY_BYTES,
    MAX_READINGS_PER_REQUEST,
    MIN_API_RELEASE,
    REQUEST_TIMEOUT_SECONDS,
)
from .readings import is_api_reading, parse_version

API_KEY_PATTERN = re.compile(r"pme_[a-f0-9]{16}_[a-f0-9]{64}")


class PowermeshError(Exception):
    """Base error with a safe code suitable for diagnostics."""

    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class PowermeshConnectionError(PowermeshError):
    """Transient transport or response failure."""


class PowermeshAuthError(PowermeshError):
    """The API key is missing, invalid or revoked."""


class PowermeshForbiddenError(PowermeshError):
    """Consent or the required permission is missing."""


class PowermeshRateLimitError(PowermeshError):
    """The API asked the client to retry later."""

    def __init__(self, code: str, retry_after: int) -> None:
        super().__init__(code, 429)
        self.retry_after = retry_after


class PowermeshOutdatedError(PowermeshError):
    """The service requires a newer integration or API version."""


class PowermeshRejectedError(PowermeshError):
    """The request was rejected and requires correction."""

    def __init__(self, code: str, status: int, body: dict[str, Any] | None) -> None:
        super().__init__(code, status)
        self.body = body


@dataclass(slots=True)
class UploadResult:
    """Server-confirmed outcome of an upload."""

    accepted: int
    duplicates: int
    remaining_requests: int | None = None


def validate_connection(api_key: str) -> None:
    """Validate the fixed production API key format without accepting URLs."""
    if not isinstance(api_key, str) or API_KEY_PATTERN.fullmatch(api_key.strip()) is None:
        raise ValueError("invalid_api_key")


def encode_request(payload: dict[str, Any]) -> bytes:
    """Serialize a request within the service's documented body limit."""
    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as err:
        raise PowermeshRejectedError("invalid_payload", 400, None) from err
    if len(encoded) > MAX_BODY_BYTES:
        raise PowermeshRejectedError("payload_too_large", 413, None)
    return encoded


class PowermeshClient:
    """Authenticated HTTPS API client using Home Assistant's shared session."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str, base_url: str = DEFAULT_URL) -> None:
        validate_connection(api_key)
        parts = urlsplit(base_url)
        if (
            parts.scheme != "https"
            or parts.hostname != "api.powermesh.de"
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
            or parts.username
            or parts.password
        ):
            raise ValueError("invalid_api_url")
        self._session = session
        self._base_url = "https://api.powermesh.de"
        self._api_key = api_key.strip()
        self.key_id = self._api_key.split("_", 2)[1]

    @property
    def base_url(self) -> str:
        """Fixed production service base URL."""
        return self._base_url

    async def status(self) -> dict[str, Any]:
        """Check credentials and service compatibility."""
        body, _ = await self._request("GET", "/api/v2/status")
        return body

    async def upload(self, readings: list[dict[str, Any]]) -> UploadResult:
        """Upload one batch and require an exact server acknowledgement."""
        if (
            not 1 <= len(readings) <= MAX_READINGS_PER_REQUEST
            or not all(is_api_reading(reading) for reading in readings)
        ):
            raise PowermeshRejectedError("invalid_readings_count", 422, None)
        body, headers = await self._request(
            "POST", "/api/v2/readings", {"readings": readings}
        )
        accepted, duplicates = body.get("accepted"), body.get("duplicates")
        if (
            type(accepted) is not int
            or type(duplicates) is not int
            or accepted < 0
            or duplicates < 0
            or accepted + duplicates != len(readings)
        ):
            raise PowermeshConnectionError("invalid_acknowledgement")
        remaining_header = headers.get("X-RateLimit-Remaining")
        remaining = int(remaining_header) if remaining_header and remaining_header.isdigit() else None
        return UploadResult(accepted, duplicates, remaining)

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], Any]:
        encoded_payload = None
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "X-Powermesh-Client": CLIENT_ID,
            "User-Agent": f"powermesh-energy-{CLIENT_ID}",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
            encoded_payload = encode_request(payload)
        try:
            async with self._session.request(
                method,
                self._base_url + path,
                data=encoded_payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
                allow_redirects=False,
            ) as response:
                status = response.status
                response_headers = response.headers
                raw = await response.content.read(MAX_BODY_BYTES + 1)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise PowermeshConnectionError("cannot_connect") from err

        if len(raw) > MAX_BODY_BYTES:
            raise PowermeshConnectionError("invalid_response")
        try:
            body = json.loads(raw) if raw else None
        except (ValueError, UnicodeError):
            body = None

        if 200 <= status < 300 and isinstance(body, dict):
            response_release = parse_version(response_headers.get("X-Powermesh-Api-Version"))
            minimum_release = parse_version(MIN_API_RELEASE)
            body_release = parse_version(body.get("api_release"))
            if (
                response_release is None
                or minimum_release is None
                or response_release < minimum_release
                or (method == "GET" and response_release != body_release)
            ):
                raise PowermeshOutdatedError("api_incompatible", status)
            if method == "POST" and body.get("status") not in (None, "ok"):
                raise PowermeshConnectionError("invalid_response")
            if method == "GET" and body.get("status") != "ok":
                raise PowermeshConnectionError("invalid_response")
            return body, response_headers

        error = body.get("error") if isinstance(body, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        code = code if isinstance(code, str) else f"http_{status}"
        if status == 401:
            raise PowermeshAuthError(code, status)
        if status == 426:
            raise PowermeshOutdatedError(code, status)
        if status == 429:
            retry_header = response_headers.get("Retry-After", "60")
            retry_after = int(retry_header) if retry_header.isdigit() else 60
            raise PowermeshRateLimitError(code, retry_after)
        if status == 403 and code in {"consent_required", "insufficient_scope"}:
            raise PowermeshForbiddenError(code, status)
        if status in {400, 413, 415, 422}:
            raise PowermeshRejectedError(code, status, body if isinstance(body, dict) else None)
        raise PowermeshConnectionError(code, status)


def validate_status(body: dict[str, Any]) -> None:
    """Reject a status response from an incompatible or malformed service."""
    client = body.get("client")
    release = parse_version(body.get("api_release"))
    minimum_release = parse_version(MIN_API_RELEASE)
    if (
        body.get("status") != "ok"
        or body.get("api_version") != API_MAJOR
        or release is None
        or minimum_release is None
        or release < minimum_release
        or not isinstance(client, dict)
        or parse_version(client.get("minimum")) is None
        or parse_version(client.get("latest")) is None
        or not isinstance(body.get("limits"), dict)
        or body["limits"].get("max_readings_per_request") != MAX_READINGS_PER_REQUEST
        or body["limits"].get("max_body_bytes") != MAX_BODY_BYTES
        or type(body["limits"].get("requests_per_minute")) is not int
        or body["limits"]["requests_per_minute"] < 1
        or type(body.get("retention_days")) is not int
        or body["retention_days"] < 1
    ):
        raise PowermeshOutdatedError("api_incompatible")
    scopes = body.get("scopes")
    if not isinstance(scopes, list) or "readings:write" not in scopes:
        raise PowermeshForbiddenError("insufficient_scope", 403)
