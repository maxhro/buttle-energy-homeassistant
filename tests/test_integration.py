"""MQTT configuration and durable uploader behavior against Home Assistant."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powermesh_energy.api import (
    PowermeshAuthError, PowermeshClient, PowermeshConnectionError,
    PowermeshRejectedError, UploadResult,
)
from custom_components.powermesh_energy.const import DOMAIN, CONF_ENTITIES, CONF_SMOOTHING, MQTT_CONTRACT
from custom_components.powermesh_energy.uploader import PowermeshUploader
from .conftest import ENERGY

CONNECTION = {CONF_HOST: "mqtt.example.invalid", CONF_PORT: 8883, CONF_USERNAME: "a" * 32, CONF_PASSWORD: "synthetic-password"}
GENERATION = "b" * 32
STATUS = {
    "contract": MQTT_CONTRACT, "ok": True, "generation": GENERATION,
    "api_release": MQTT_CONTRACT, "client": {"minimum": MQTT_CONTRACT, "latest": MQTT_CONTRACT},
    "limits": {"max_readings_per_request": 200, "max_body_bytes": 131072, "requests_per_minute": 100},
    "retention_days": 365,
}


def reading(value=1):
    return {
        "entity_id": "sensor.grid_import", "timestamp": dt_util.utcnow().replace(microsecond=0).isoformat(),
        "value": value, "unit": "kWh", "device_class": "energy", "state_class": "total_increasing",
    }


def make_uploader(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=CONNECTION, options={
        CONF_ENTITIES: ["sensor.grid_import"], CONF_SMOOTHING: {"sensor.grid_import": "none"},
    })
    entry.add_to_hass(hass)
    client = AsyncMock(spec=PowermeshClient)
    client.username = CONNECTION[CONF_USERNAME]
    client.base_url = "https://powermesh.de"
    client.status.return_value = deepcopy(STATUS)
    client.upload.return_value = UploadResult(1, 0)
    uploader = PowermeshUploader(hass, entry, client)
    entry.runtime_data = uploader
    uploader._store = AsyncMock()
    uploader._generation = GENERATION
    uploader._buffer_owner = client.username
    return uploader, client, entry


async def test_config_flow_and_smoothing(hass):
    hass.states.async_set("sensor.grid_import", "10", ENERGY)
    with patch("custom_components.powermesh_energy.config_flow.PowermeshClient") as client:
        client.return_value.status = AsyncMock(return_value=STATUS)
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        assert CONF_HOST in result["data_schema"].schema
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CONNECTION)
        assert result["step_id"] == "entities"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_ENTITIES: ["sensor.grid_import"]})
        assert result["step_id"] == "smoothing"
        with patch("custom_components.powermesh_energy.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == CONNECTION
        assert result["options"][CONF_SMOOTHING] == {"sensor.grid_import": "mean_1min"}


@pytest.mark.parametrize("error,expected", [
    (PowermeshAuthError("access_revoked"), "invalid_auth"),
    (PowermeshConnectionError("cannot_connect"), "cannot_connect"),
])
async def test_config_errors(hass, error, expected):
    with patch("custom_components.powermesh_energy.config_flow.PowermeshClient") as client:
        client.return_value.status = AsyncMock(side_effect=error)
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CONNECTION)
        assert result["errors"] == {"base": expected}


async def test_batch_saved_before_publish_and_timeout_retry_is_identical(hass):
    uploader, client, _ = make_uploader(hass)
    uploader._append(reading())
    sent = []

    async def upload(request):
        assert uploader._store.async_save.call_args.args[0]["inflight"] == request
        sent.append(deepcopy(request))
        if len(sent) == 1:
            raise PowermeshConnectionError("timeout")
        return UploadResult(1, 0)

    client.upload.side_effect = upload
    await uploader.async_upload()
    assert uploader.pending == 1
    assert uploader._inflight is not None
    uploader._retry_at = dt_util.utcnow() - timedelta(seconds=1)
    await uploader.async_upload()
    assert sent[0] == sent[1]
    assert uploader.pending == 0
    assert uploader.accepted_total == 1
    assert uploader._store.async_save.call_args.args[0]["inflight"] is None


async def test_restart_reuses_persisted_batch(hass):
    uploader, client, _ = make_uploader(hass)
    uploader._append(reading())
    client.upload.side_effect = PowermeshConnectionError("timeout")
    await uploader.async_upload()
    saved = uploader._data()
    replacement, replacement_client, _ = make_uploader(hass)
    replacement._store.async_load.return_value = saved
    await replacement.async_start()
    await hass.async_block_till_done()
    assert replacement_client.upload.call_args.args[0] == saved["inflight"]
    assert replacement.pending == 0
    await replacement.async_stop()


async def test_new_reading_during_publish_is_not_removed(hass):
    uploader, client, _ = make_uploader(hass)
    uploader._append(reading(1))
    sent = []

    async def upload(request):
        sent.append(deepcopy(request))
        if len(sent) == 1:
            uploader._append(reading(2))
        return UploadResult(1, 0)

    client.upload.side_effect = upload
    await uploader.async_upload()
    assert [batch["readings"][0]["value"] for batch in sent] == [1, 2]
    assert uploader.pending == 0


@pytest.mark.parametrize("changed", ["generation", "owner"])
async def test_changed_generation_or_credential_never_rebinds_buffer(hass, changed):
    uploader, client, entry = make_uploader(hass)
    uploader._append(reading())
    if changed == "generation":
        client.status.return_value = STATUS | {"generation": "c" * 32}
    else:
        client.username = "d" * 32
    await uploader.async_upload()
    client.upload.assert_not_awaited()
    assert uploader.pending == 1 and uploader._paused
    assert uploader.last_error == "buffer_generation_changed"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"buffer_generation_changed_{entry.entry_id}")


async def test_permanent_rejection_keeps_batch_and_stops(hass):
    uploader, client, _ = make_uploader(hass)
    uploader._append(reading())
    client.upload.side_effect = PowermeshRejectedError("invalid_readings", {"error": {"code": "invalid_readings"}})
    await uploader.async_upload()
    assert uploader.pending == 1 and uploader._paused
    assert uploader.dropped_total == 0
    assert uploader._inflight is not None


async def test_revoked_client_reauth_keeps_data(hass):
    uploader, client, entry = make_uploader(hass)
    uploader._append(reading())
    client.upload.side_effect = PowermeshAuthError("access_revoked")
    with patch.object(entry, "async_start_reauth") as reauth:
        await uploader.async_upload()
    reauth.assert_called_once()
    assert uploader.pending == 1 and uploader._paused


async def test_unbound_legacy_buffer_is_preserved_but_not_sent(hass):
    uploader, client, _ = make_uploader(hass)
    uploader._store.async_load.return_value = {"readings": [reading()]}
    await uploader.async_start()
    assert uploader._paused and uploader.pending == 1
    client.upload.assert_not_awaited()


async def test_setup_and_unload_without_network(hass):
    with patch("custom_components.powermesh_energy.PowermeshClient") as client:
        client.return_value = AsyncMock(spec=PowermeshClient)
        client.return_value.username = CONNECTION[CONF_USERNAME]
        client.return_value.status.return_value = STATUS
        entry = MockConfigEntry(domain=DOMAIN, data=CONNECTION, options={CONF_ENTITIES: []})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reauth_updates_credentials_without_removing_buffer(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=CONNECTION, unique_id="old")
    entry.add_to_hass(hass)
    with patch("custom_components.powermesh_energy.config_flow.PowermeshClient") as client:
        client.return_value.status = AsyncMock(return_value=STATUS)
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=CONNECTION,
        )
        assert result["step_id"] == "reauth_confirm"
        replacement = CONNECTION | {CONF_USERNAME: "f" * 32}
        with patch.object(hass.config_entries, "async_reload", return_value=True):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], replacement)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data == replacement


async def test_diagnostics_redact_all_credentials_and_no_values(hass):
    from custom_components.powermesh_energy.diagnostics import async_get_config_entry_diagnostics

    uploader, _, entry = make_uploader(hass)
    uploader._append(reading(987654.321))
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["entry"][CONF_USERNAME] == "**REDACTED**"
    assert data["entry"][CONF_PASSWORD] == "**REDACTED**"
    assert "987654.321" not in str(data)


async def test_save_failure_prevents_publish(hass):
    uploader, client, _ = make_uploader(hass)
    uploader._append(reading())
    uploader._store.async_save.side_effect = OSError("synthetic disk failure")
    with pytest.raises(OSError, match="synthetic disk failure"):
        await uploader.async_upload()
    client.upload.assert_not_awaited()
    assert uploader.pending == 1


async def test_stop_cancels_active_upload_and_persists_same_batch(hass):
    import asyncio

    uploader, client, _ = make_uploader(hass)
    uploader._append(reading())
    entered = asyncio.Event()

    async def waiting(request):
        entered.set()
        await asyncio.Event().wait()

    client.upload.side_effect = waiting
    task = asyncio.create_task(uploader.async_upload())
    await entered.wait()
    batch = deepcopy(uploader._inflight)
    await uploader.async_stop()
    assert task.cancelled()
    assert uploader._store.async_save.call_args.args[0]["inflight"] == batch
    assert uploader.pending == 1
