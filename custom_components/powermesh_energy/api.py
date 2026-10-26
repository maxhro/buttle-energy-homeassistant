"""Client for powermesh.de."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .const import CLIENT_ID, REQUEST_TIMEOUT_SECONDS


class PowermeshError(Exception):
    """Base error; ``code`` is the server error code or a local reason."""

    def __init__(self, code: str, message: str = "", status: int | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.status = status


class PowermeshConnectionError(PowermeshError):
    """Temporary problem; retry later."""


class PowermeshAuthError(PowermeshError):
    """The API key is missing, invalid or revoked."""


class PowermeshForbiddenError(PowermeshError):
    """Consent or scope missing."""


class PowermeshRateLimitError(PowermeshError):
    """Throttled; ``retry_after`` in seconds."""

    def __init__(self, code: str, message: str, retry_after: int) -> None:
        super().__init__(code, message, 429)
        self.retry_after = retry_after


class PowermeshOutdatedError(PowermeshError):
    """The server no longer accepts this integration version."""


class PowermeshRejectedError(PowermeshError):
    """Readings were rejected."""

    def __init__(self, code: str, message: str, status: int, body: dict[str, Any] | None) -> None:
        super().__init__(code, message, status)
        self.body = body


@dataclass(slots=True)
class UploadResult:
    """Outcome of a successful upload."""

    accepted: int
    duplicates: int
    remaining_requests: int | None


def normalize_url(url: str) -> str:
    """Validate the base URL. HTTPS is required except for local test servers."""
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("https_required")
    if not parts.hostname or parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("invalid_url")
    return f"{parts.scheme}://{parts.netloc}"


class PowermeshClient:
    """Authenticated powermesh.de session."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, api_key: str) -> None:
        self._session = session
        self._base_url = normalize_url(base_url)
        self._api_key = api_key.strip()

    @property
    def base_url(self) -> str:
        """Normalized server URL."""
        return self._base_url

    async def status(self) -> dict[str, Any]:
        """Verify the credentials and return server information."""
        body, _ = await self._request("GET", "/api/v2/status")
        return body

    async def upload(self, readings: list[dict[str, Any]]) -> UploadResult:
        """Send a batch of readings."""
        body, headers = await self._request("POST", "/api/v2/readings", {"readings": readings})
        remaining = headers.get("X-RateLimit-Remaining")
        return UploadResult(
            accepted=int(body.get("accepted", 0)),
            duplicates=int(body.get("duplicates", 0)),
            remaining_requests=int(remaining) if remaining and remaining.isdigit() else None,
        )

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], Any]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json", "X-Powermesh-Client": CLIENT_ID, "User-Agent": f"powermesh-energy-{CLIENT_ID}"}
        try:
            async with self._session.request(
                method,
                self._base_url + path,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
                allow_redirects=False,
            ) as response:
                try:
                    body = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    body = None
                status = response.status
                response_headers = response.headers
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PowermeshConnectionError("cannot_connect", str(err)) from err

        if 200 <= status < 300 and isinstance(body, dict):
            return body, response_headers
        error = body.get("error") if isinstance(body, dict) else None
        code = str(error.get("code")) if isinstance(error, dict) else f"http_{status}"
        message = str(error.get("message", "")) if isinstance(error, dict) else ""
        if status == 401:
            raise PowermeshAuthError(code, message, status)
        if status == 426:
            raise PowermeshOutdatedError(code, message, status)
        if status == 429:
            retry = response_headers.get("Retry-After", "60")
            raise PowermeshRateLimitError(code, message, int(retry) if retry.isdigit() else 60)
        if status == 403 and code in {"consent_required", "insufficient_scope"}:
            raise PowermeshForbiddenError(code, message, status)
        if status == 422 and isinstance(body, dict):
            raise PowermeshRejectedError(code, message, status, body)
        # Anything else (maintenance, redirects, proxies) is treated as temporary so no data is lost.
        raise PowermeshConnectionError(code, message, status)
