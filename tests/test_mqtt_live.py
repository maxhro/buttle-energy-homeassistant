"""Opt-in, isolated local transport/uploader acceptance; never a production probe."""

from copy import deepcopy
import os
import ssl
from urllib.parse import urlsplit

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powermesh_energy.api import PowermeshClient, UploadResult
from custom_components.powermesh_energy.const import DOMAIN, CONF_ENTITIES, CONF_SMOOTHING
from custom_components.powermesh_energy.uploader import PowermeshUploader
from .test_integration import reading

pytestmark = pytest.mark.skipif(
    os.environ.get("POWERMESH_LIVE_TEST") != "1",
    reason="Explicit isolated local MQTT/MySQL harness required",
)


async def test_real_uploader_and_storage_confirmation(hass, socket_enabled):
    url = urlsplit(os.environ["MQTT_TEST_URL"])
    if url.scheme != "mqtts" or url.hostname not in {"localhost", "127.0.0.1"}:
        pytest.fail("Live test refuses non-loopback or non-TLS broker")
    username = os.environ["HA_TEST_USERNAME"]
    password = os.environ["HA_TEST_PASSWORD"]
    context = ssl.create_default_context(cafile=os.environ["MQTT_TEST_CA"])

    class RecordingClient(PowermeshClient):
        sent = None

        async def upload(self, request):
            self.sent = deepcopy(request)
            return await super().upload(request)

    client = RecordingClient(url.hostname, url.port, username, password, tls_context=context)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: url.hostname, CONF_PORT: url.port, CONF_USERNAME: username, CONF_PASSWORD: password},
        options={CONF_ENTITIES: ["sensor.ha_live_energy"], CONF_SMOOTHING: {"sensor.ha_live_energy": "none"}},
    )
    entry.add_to_hass(hass)
    uploader = PowermeshUploader(hass, entry, client)
    entry.runtime_data = uploader
    assert await uploader.async_check_version()
    value = reading(37.5) | {"entity_id": "sensor.ha_live_energy"}
    uploader._append(value)
    await uploader.async_upload()
    assert uploader.pending == 0
    assert uploader.accepted_total == 1
    assert uploader.last_error is None
    assert client.sent is not None
    stored = await uploader._store.async_load()
    assert stored["inflight"] is None and stored["readings"] == []
    replay = await client.upload(deepcopy(client.sent))
    assert replay == UploadResult(1, 0)
    await uploader.async_stop()
