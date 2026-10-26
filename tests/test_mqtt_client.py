"""Transport tests: subscription, TLS and application-level confirmation."""

import asyncio
from collections import deque
import json
import ssl
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.powermesh_energy.api import (
    PowermeshClient, PowermeshConnectionError, PowermeshAuthError,
    PowermeshRejectedError, validate_connection,
)
from custom_components.powermesh_energy.const import MQTT_CONTRACT
from .test_integration import STATUS, CONNECTION


class FakeBrokerClient:
    options = {}
    reply = {}
    retained = False
    only_puback = False
    seen = []

    def __init__(self, *args, **kwargs):
        type(self).options = kwargs
        self.queue = deque()
        self.subscribed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def subscribe(self, topic, qos):
        assert qos == 1
        self.topic = topic
        self.subscribed = True

    async def publish(self, topic, payload, qos, retain):
        assert self.subscribed and qos == 1 and retain is False
        request = json.loads(payload)
        type(self).seen.append(request)
        if not self.only_puback:
            response = {"contract": MQTT_CONTRACT, "id": request["id"], "ok": True} | self.reply
            self.queue.append(SimpleNamespace(topic=self.topic, payload=json.dumps(response).encode(), retain=self.retained))

    @property
    def messages(self):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.queue:
            return self.queue.popleft()
        await asyncio.sleep(30)
        raise StopAsyncIteration


@pytest.fixture
def mqtt():
    FakeBrokerClient.reply = {}
    FakeBrokerClient.retained = False
    FakeBrokerClient.only_puback = False
    FakeBrokerClient.seen = []
    with patch("custom_components.powermesh_energy.api.aiomqtt.Client", FakeBrokerClient):
        yield FakeBrokerClient


def client():
    return PowermeshClient(CONNECTION["host"], CONNECTION["port"], CONNECTION["username"], CONNECTION["password"])


def request():
    return {"contract": MQTT_CONTRACT, "id": "c" * 32, "operation": "readings", "generation": "b" * 32, "readings": [{}]}


async def test_tls_clean_session_and_status(mqtt):
    mqtt.reply = STATUS
    body = await client().status()
    assert body["generation"] == "b" * 32
    assert mqtt.options["clean_start"] is True
    assert mqtt.options["properties"].SessionExpiryInterval == 0
    assert mqtt.options["tls_context"].verify_mode == ssl.CERT_REQUIRED
    assert mqtt.options["tls_context"].check_hostname


@pytest.mark.parametrize("retained", [False, True])
async def test_puback_or_retained_reply_never_confirms_storage(mqtt, retained):
    mqtt.retained = retained
    mqtt.only_puback = not retained
    with patch("custom_components.powermesh_energy.api.REQUEST_TIMEOUT_SECONDS", 0.05):
        with pytest.raises(PowermeshConnectionError):
            await client().upload(request())


@pytest.mark.parametrize("response", [
    {}, {"accepted": 1, "duplicates": -1},
    {"accepted": True, "duplicates": 0}, {"accepted": 0, "duplicates": 0},
])
async def test_malformed_storage_ack_keeps_pending(response, mqtt):
    mqtt.reply = response
    with pytest.raises(PowermeshConnectionError):
        await client().upload(request())


async def test_actual_matching_storage_ack(mqtt):
    mqtt.reply = {"accepted": 1, "duplicates": 0}
    result = await client().upload(request())
    assert result.accepted == 1 and result.duplicates == 0


async def test_access_revoked_is_not_transient(mqtt):
    mqtt.reply = {"ok": False, "error": {"code": "access_revoked"}}
    with pytest.raises(PowermeshAuthError):
        await client().upload(request())


@pytest.mark.parametrize("host,port,username", [
    ("mqtts://host", 8883, "a" * 32), ("host", 0, "a" * 32), ("host", True, "a" * 32),
    ("host", 8883, "user@email"), ("host/path", 8883, "a" * 32),
])
def test_invalid_connection(host, port, username):
    with pytest.raises(ValueError):
        validate_connection(host, port, username, "synthetic")


def test_disabling_tls_validation_is_impossible():
    context = ssl._create_unverified_context()
    with pytest.raises(ValueError, match="tls_verification_required"):
        PowermeshClient("localhost", 8883, "a" * 32, "synthetic", tls_context=context)
