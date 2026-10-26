"""MQTT transport. Broker acknowledgement is never a storage acknowledgement."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
import ssl
from typing import Any
from uuid import uuid4

import aiomqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from .const import MAX_BODY_BYTES, MQTT_CONTRACT, REQUEST_TIMEOUT_SECONDS

HEX_ID = re.compile(r"[a-f0-9]{32}")


class PowermeshError(Exception):
    """A sanitized transport or application failure."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class PowermeshConnectionError(PowermeshError):
    """Transient failure; keep pending readings."""


class PowermeshAuthError(PowermeshError):
    """Revoked or invalid credentials."""


class PowermeshForbiddenError(PowermeshError):
    """Current consent is missing."""


class PowermeshOutdatedError(PowermeshError):
    """Unsupported protocol."""


class PowermeshRateLimitError(PowermeshError):
    """Retry later without changing the pending batch."""

    def __init__(self, code: str, retry_after: int) -> None:
        super().__init__(code)
        self.retry_after = retry_after


class PowermeshRejectedError(PowermeshError):
    """Permanent batch rejection requiring explicit handling."""

    def __init__(self, code: str, body: dict[str, Any]) -> None:
        super().__init__(code)
        self.body = body


@dataclass(slots=True)
class UploadResult:
    accepted: int
    duplicates: int
    remaining_requests: int | None = None


def validate_connection(host: str, port: int, username: str, password: str) -> None:
    """Reject URLs, paths and malformed credential identifiers."""
    if (
        not isinstance(host, str) or not host or host != host.strip()
        or any(char in host for char in "/:@ \t\r\n")
        or not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535
        or not isinstance(username, str) or HEX_ID.fullmatch(username) is None
        or not isinstance(password, str) or not password
    ):
        raise ValueError("invalid_connection")


def encode_request(request: dict[str, Any]) -> bytes:
    try:
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as err:
        raise PowermeshRejectedError("invalid_payload", {}) from err
    if len(payload) > MAX_BODY_BYTES:
        raise PowermeshRejectedError("payload_too_large", {})
    return payload


class PowermeshClient:
    """One bounded TLS session per exchange, independent of HA's local broker."""

    def __init__(
        self, host: str, port: int, username: str, password: str,
        *, tls_context: ssl.SSLContext | None = None,
    ) -> None:
        validate_connection(host, port, username, password)
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self._tls = tls_context
        if self._tls is not None and (self._tls.verify_mode != ssl.CERT_REQUIRED or not self._tls.check_hostname):
            raise ValueError("tls_verification_required")
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return "https://powermesh.de"

    async def status(self) -> dict[str, Any]:
        body = await self._request({"contract": MQTT_CONTRACT, "id": uuid4().hex, "operation": "status"})
        limits = body.get("limits")
        client = body.get("client")
        if (
            not isinstance(body.get("generation"), str)
            or HEX_ID.fullmatch(body["generation"]) is None
            or body.get("api_release") != MQTT_CONTRACT
            or not isinstance(client, dict)
            or client.get("minimum") != MQTT_CONTRACT
            or not isinstance(client.get("latest"), str)
            or not isinstance(limits, dict)
            or limits.get("max_readings_per_request") != 200
            or limits.get("max_body_bytes") != MAX_BODY_BYTES
            or type(limits.get("requests_per_minute")) is not int
            or limits["requests_per_minute"] < 1
            or type(body.get("retention_days")) is not int
            or body["retention_days"] < 1
        ):
            raise PowermeshOutdatedError("api_incompatible")
        return body

    async def upload(self, request: dict[str, Any]) -> UploadResult:
        body = await self._request(request)
        accepted, duplicates = body.get("accepted"), body.get("duplicates")
        if (
            type(accepted) is not int or type(duplicates) is not int
            or accepted < 0 or duplicates < 0
            or accepted + duplicates != len(request["readings"])
        ):
            raise PowermeshConnectionError("invalid_acknowledgement")
        return UploadResult(accepted, duplicates)

    async def _request(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = encode_request(request)
        properties = Properties(PacketTypes.CONNECT)
        properties.SessionExpiryInterval = 0
        async with self._lock:
            if self._tls is None:
                self._tls = await asyncio.to_thread(ssl.create_default_context)
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                    async with aiomqtt.Client(
                        self.host, port=self.port, username=self.username, password=self._password,
                        identifier=f"powermesh-{uuid4().hex}", protocol=aiomqtt.ProtocolVersion.V5,
                        tls_context=self._tls, clean_start=True, properties=properties,
                        timeout=REQUEST_TIMEOUT_SECONDS, max_queued_incoming_messages=20,
                    ) as client:
                        output = f"powermesh/prototype/{self.username}/out"
                        await client.subscribe(output, qos=1)
                        await client.publish(
                            f"powermesh/prototype/{self.username}/in", payload,
                            qos=1, retain=False,
                        )
                        async for message in client.messages:
                            if str(message.topic) != output or message.retain:
                                continue
                            raw = message.payload
                            if not isinstance(raw, bytes) or len(raw) > MAX_BODY_BYTES:
                                raise PowermeshConnectionError("invalid_response")
                            try:
                                body = json.loads(raw)
                            except (ValueError, UnicodeError) as err:
                                raise PowermeshConnectionError("invalid_response") from err
                            if not isinstance(body, dict) or body.get("id") != request["id"]:
                                continue
                            return self._response(body)
                        raise PowermeshConnectionError("connection_closed")
            except aiomqtt.MqttCodeError as err:
                if getattr(err.rc, "value", err.rc) in (4, 5, 134, 135):
                    raise PowermeshAuthError("invalid_auth") from err
                raise PowermeshConnectionError("cannot_connect") from err
            except (aiomqtt.MqttError, TimeoutError, OSError) as err:
                raise PowermeshConnectionError("cannot_connect") from err

    @staticmethod
    def _response(body: dict[str, Any]) -> dict[str, Any]:
        if body.get("contract") != MQTT_CONTRACT:
            raise PowermeshOutdatedError("api_incompatible")
        if body.get("ok") is True:
            return body
        error = body.get("error")
        if body.get("ok") is not False or not isinstance(error, dict) or not isinstance(error.get("code"), str):
            raise PowermeshConnectionError("invalid_response")
        code = error["code"]
        if code in {"access_revoked", "invalid_token", "invalid_auth"}:
            raise PowermeshAuthError(code)
        if code == "consent_required":
            raise PowermeshForbiddenError(code)
        if code == "rate_limited":
            seconds = body.get("retry_after", 60)
            raise PowermeshRateLimitError(code, seconds if type(seconds) is int else 60)
        if code == "service_unavailable":
            raise PowermeshConnectionError(code)
        raise PowermeshRejectedError(code, body)
