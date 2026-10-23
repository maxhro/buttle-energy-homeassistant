"""Config flow, options flow and uploader against a real Home Assistant core."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.components.energy.data import async_get_manager
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.buttle_energy.const import CONF_ENTITIES, CONF_USE_SUGGESTION, DOMAIN, VERSION

from .conftest import API_KEY, ENERGY, GAS, POWER, STATUS_BODY, URL

READINGS_URL = f"{URL}/api/v1/readings"
STATUS_URL = f"{URL}/api/v1/status"


async def _dashboard(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.grid_import", "100.5", ENERGY)
    hass.states.async_set("sensor.grid_export", "20", ENERGY)
    hass.states.async_set("sensor.pv_power", "1500", POWER)
    hass.states.async_set("sensor.gas", "3.2", GAS)
    hass.states.async_set("sensor.other_power", "50", POWER)
    manager = await async_get_manager(hass)
    await manager.async_update(
        {
            "energy_sources": [
                {
                    "type": "grid",
                    "flow_from": [{"stat_energy_from": "sensor.grid_import", "stat_cost": None, "entity_energy_price": None, "number_energy_price": None}],
                    "flow_to": [{"stat_energy_to": "sensor.grid_export", "stat_compensation": None, "entity_energy_price": None, "number_energy_price": None}],
                    "cost_adjustment_day": 0,
                },
                {"type": "solar", "stat_energy_from": "sensor.pv_energy_missing", "config_entry_solar_forecast": None},
                {"type": "gas", "stat_energy_from": "sensor.gas", "stat_cost": None, "entity_energy_price": None, "number_energy_price": None},
            ],
            "device_consumption": [{"stat_consumption": "sensor.grid_import"}],
        }
    )


async def test_config_flow_uses_dashboard_suggestion(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    await _dashboard(hass)
    aioclient_mock.get(f"{URL}/api/v1/status", json=STATUS_BODY)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: URL + "/", CONF_API_KEY: API_KEY})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "entities"
    assert "sensor.grid_import" in result["description_placeholders"]["suggestion"]
    assert "sensor.gas" in result["description_placeholders"]["skipped"]
    default = next(k.default() for k in result["data_schema"].schema if k == CONF_ENTITIES)
    assert default == ["sensor.grid_import", "sensor.grid_export"]
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == f"Bearer {API_KEY}"
    assert aioclient_mock.mock_calls[0][3]["X-Buttle-Client"] == f"homeassistant/{VERSION}"

    with patch("custom_components.buttle_energy.async_setup_entry", return_value=True):
        bad = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_ENTITIES: ["sensor.gas"]})
        assert bad["errors"] == {"base": "incompatible"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENTITIES: ["sensor.grid_import", "sensor.other_power"]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_URL: URL, CONF_API_KEY: API_KEY}
    assert result["options"] == {CONF_ENTITIES: ["sensor.grid_import", "sensor.other_power"]}


@pytest.mark.parametrize(
    ("status", "body", "user_input", "error"),
    [
        (401, {"error": {"code": "invalid_token"}}, {}, {"base": "invalid_auth"}),
        (403, {"error": {"code": "consent_required"}}, {}, {"base": "consent_required"}),
        (429, {"error": {"code": "rate_limited"}}, {}, {"base": "rate_limited"}),
        (503, {"error": {"code": "service_unavailable"}}, {}, {"base": "cannot_connect"}),
        (200, STATUS_BODY, {CONF_API_KEY: "secret"}, {CONF_API_KEY: "invalid_key_format"}),
        (200, STATUS_BODY, {CONF_URL: "http://buttle.test"}, {CONF_URL: "https_required"}),
        (426, {"error": {"code": "client_outdated"}}, {}, {"base": "update_required"}),
        (200, STATUS_BODY | {"client": {"minimum": "9.0.0", "latest": "9.0.0"}}, {}, {"base": "update_required"}),
        (200, STATUS_BODY | {"api_release": "1.0.0"}, {}, {"base": "api_incompatible"}),
        (200, STATUS_BODY | {"api_version": 2, "api_release": "2.0.0"}, {}, {"base": "api_incompatible"}),
    ],
)
async def test_config_flow_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int, body: dict, user_input: dict, error: dict
) -> None:
    aioclient_mock.get(f"{URL}/api/v1/status", status=status, json=body)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_API_KEY: API_KEY} | user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == error


def _entry(
    hass: HomeAssistant, entities: list[str], aioclient_mock: AiohttpClientMocker | None = None, status: dict | None = None
) -> MockConfigEntry:
    if aioclient_mock is not None:
        aioclient_mock.get(STATUS_URL, json=status or STATUS_BODY)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=URL,
        data={CONF_URL: URL, CONF_API_KEY: API_KEY},
        options={CONF_ENTITIES: entities},
    )
    entry.add_to_hass(hass)
    return entry


async def _flush(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_upload()
    await hass.async_block_till_done()


def _posted(aioclient_mock: AiohttpClientMocker) -> list[list[dict[str, Any]]]:
    return [call[2]["readings"] for call in aioclient_mock.mock_calls if call[0].upper() == "POST"]


async def test_uploader_sends_six_fields_and_sensors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    hass.states.async_set("sensor.grid_import", "100.5", ENERGY | {"friendly_name": "Netzbezug"})
    aioclient_mock.post(READINGS_URL, json={"accepted": 1, "duplicates": 0}, headers={"X-RateLimit-Remaining": "59"})
    entry = _entry(hass, ["sensor.grid_import"], aioclient_mock)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    batches = _posted(aioclient_mock)
    assert len(batches) == 1
    assert batches[0][0]["value"] == 100.5
    assert set(batches[0][0]) == {"entity_id", "timestamp", "value", "unit", "device_class", "state_class"}

    hass.states.async_set("sensor.grid_import", "unavailable", ENERGY)
    hass.states.async_set("sensor.grid_import", "101", ENERGY)
    await hass.async_block_till_done()
    assert entry.runtime_data.pending == 1
    await _flush(hass, entry)
    assert _posted(aioclient_mock)[-1][0]["value"] == 101
    assert entry.runtime_data.pending == 0

    status = hass.states.get("sensor.buttle_de_upload_status")
    assert status is not None and status.state == "ok"
    assert hass.states.get("sensor.buttle_de_pending_readings").state == "0"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_uploader_keeps_data_offline_and_drops_invalid(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    hass.states.async_set("sensor.a", "1", POWER)
    hass.states.async_set("sensor.b", "2", POWER)
    aioclient_mock.post(READINGS_URL, status=404, json={"error": {"code": "not_found"}})
    entry = _entry(hass, ["sensor.a", "sensor.b"], aioclient_mock)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    uploader = entry.runtime_data
    assert uploader.status == "offline"
    assert uploader.pending == 2

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        READINGS_URL,
        status=422,
        json={"error": {"code": "invalid_readings", "details": [{"index": 0, "field": "timestamp", "message": "x"}]}},
    )
    await _flush(hass, entry)
    posted = _posted(aioclient_mock)
    # Only index 0 is dropped; the other reading is resent alone (and rejected again by the mock).
    assert [len(batch) for batch in posted] == [2, 1]
    assert posted[1][0] == posted[0][1]
    assert uploader.dropped_total == 2
    assert uploader.pending == 0
    assert uploader.status == "rejected"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_uploader_handles_consent_rate_limit_and_auth(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    hass.states.async_set("sensor.a", "1", POWER)
    aioclient_mock.post(READINGS_URL, status=403, json={"error": {"code": "consent_required"}})
    entry = _entry(hass, ["sensor.a"], aioclient_mock)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    uploader = entry.runtime_data
    assert uploader.status == "consent_required"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"consent_{entry.entry_id}") is not None

    aioclient_mock.clear_requests()
    aioclient_mock.post(READINGS_URL, status=429, json={"error": {"code": "rate_limited"}}, headers={"Retry-After": "120"})
    await _flush(hass, entry)
    assert uploader.status == "rate_limited"
    await _flush(hass, entry)
    assert len(_posted(aioclient_mock)) == 1, "Retry-After must be respected"

    uploader._retry_at = None
    aioclient_mock.clear_requests()
    aioclient_mock.post(READINGS_URL, status=401, json={"error": {"code": "invalid_token"}})
    await _flush(hass, entry)
    assert uploader.status == "auth_failed"
    assert uploader.pending == 1
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flows and flows[0]["context"]["source"] == config_entries.SOURCE_REAUTH


async def test_reauth_updates_key(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = _entry(hass, ["sensor.a"])
    new_key = "bte_" + "fedcba9876543210" + "_" + "b" * 64
    aioclient_mock.get(f"{URL}/api/v1/status", json=STATUS_BODY)
    with patch("custom_components.buttle_energy.async_setup_entry", return_value=True):
        result = await entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: new_key})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == new_key


async def test_options_flow_reset_to_suggestion(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    await _dashboard(hass)
    entry = _entry(hass, ["sensor.other_power"])
    with patch("custom_components.buttle_energy.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        default = next(k.default() for k in result["data_schema"].schema if k == CONF_ENTITIES)
        assert default == ["sensor.other_power"]
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ENTITIES: ["sensor.other_power"], CONF_USE_SUGGESTION: True}
        )
        assert result["type"] is FlowResultType.FORM
        default = next(k.default() for k in result["data_schema"].schema if k == CONF_ENTITIES)
        assert default == ["sensor.grid_import", "sensor.grid_export"]
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ENTITIES: default, CONF_USE_SUGGESTION: False}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_ENTITIES: ["sensor.grid_import", "sensor.grid_export"]}


async def test_diagnostics_redacts_key(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    from custom_components.buttle_energy.diagnostics import async_get_config_entry_diagnostics

    aioclient_mock.post(READINGS_URL, json={"accepted": 0, "duplicates": 0})
    entry = _entry(hass, [], aioclient_mock)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert API_KEY not in str(diagnostics)
    assert diagnostics["entry"][CONF_API_KEY] == "**REDACTED**"
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_version_matches_manifest() -> None:
    import json
    from pathlib import Path

    manifest = json.loads((Path(__file__).parents[1] / "custom_components/buttle_energy/manifest.json").read_text())
    assert manifest["version"] == VERSION


async def test_uploader_pauses_when_update_required(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    hass.states.async_set("sensor.a", "1", POWER)
    aioclient_mock.post(READINGS_URL, json={"accepted": 1, "duplicates": 0})
    entry = _entry(hass, ["sensor.a"], aioclient_mock, STATUS_BODY | {"client": {"minimum": "9.0.0", "latest": "9.1.0"}})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    uploader = entry.runtime_data
    assert uploader.status == "update_required"
    assert uploader.pending == 1
    assert _posted(aioclient_mock) == []
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"update_required_{entry.entry_id}") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_uploader_reports_available_update_and_426(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    hass.states.async_set("sensor.a", "1", POWER)
    aioclient_mock.post(READINGS_URL, status=426, json={"error": {"code": "client_outdated"}})
    entry = _entry(hass, ["sensor.a"], aioclient_mock, STATUS_BODY | {"client": {"minimum": "0.1.0", "latest": "0.9.0"}})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    uploader = entry.runtime_data
    issues = ir.async_get(hass)
    assert uploader.latest_version == "0.9.0" and uploader.server_release == "1.1.0"
    assert issues.async_get_issue(DOMAIN, f"update_available_{entry.entry_id}") is not None
    assert uploader.status == "update_required"
    assert issues.async_get_issue(DOMAIN, f"update_required_{entry.entry_id}") is not None
    assert uploader.pending == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
