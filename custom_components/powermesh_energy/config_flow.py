"""Config and options flow for Powermesh Energie."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    PowermeshAuthError,
    PowermeshClient,
    PowermeshConnectionError,
    PowermeshError,
    PowermeshForbiddenError,
    PowermeshOutdatedError,
    PowermeshRateLimitError,
    validate_connection,
)
from .const import (
    CONF_ENTITIES,
    CONF_SMOOTHING,
    CONF_UPLOAD_INTERVAL,
    CONF_USE_SUGGESTION,
    DEFAULT_UPLOAD_INTERVAL,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DOMAIN,
    INTERVAL_OPTIONS,
)
from .energy_dashboard import async_suggestion
from .readings import incompatibility
from .smoothing import OPTIONS as SMOOTHING_OPTIONS, option_for

REASONS_DE = {
    "external_statistic": "externe Statistik, keine Entität",
    "missing": "derzeit kein Zustand",
    "entity_id": "keine sensor-Entität",
    "device_class": "Geräteklasse nicht energy/power",
    "unit": "Einheit nicht unterstützt",
    "state_class": "Zustandsklasse nicht unterstützt",
}


async def _async_validate(data: Mapping[str, Any]) -> dict[str, str]:
    """Check credentials with a TLS MQTT application status exchange."""
    try:
        validate_connection(data[CONF_HOST], data[CONF_PORT], data[CONF_USERNAME], data[CONF_PASSWORD])
    except (ValueError, KeyError):
        return {"base": "invalid_connection"}
    try:
        await PowermeshClient(data[CONF_HOST], data[CONF_PORT], data[CONF_USERNAME], data[CONF_PASSWORD]).status()
    except PowermeshOutdatedError:
        return {"base": "api_incompatible"}
    except PowermeshAuthError:
        return {"base": "invalid_auth"}
    except PowermeshForbiddenError:
        return {"base": "consent_required"}
    except PowermeshRateLimitError:
        return {"base": "rate_limited"}
    except PowermeshConnectionError:
        return {"base": "cannot_connect"}
    except PowermeshError:
        return {"base": "unknown"}
    return {}


def _connection_schema(data: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_HOST, default=data.get(CONF_HOST, DEFAULT_HOST)): str,
        vol.Required(CONF_PORT, default=data.get(CONF_PORT, DEFAULT_PORT)): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "")): str,
        vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
    })


def _entity_schema(default_entities: list[str], default_interval: str = DEFAULT_UPLOAD_INTERVAL) -> vol.Schema:
    if default_interval not in INTERVAL_OPTIONS:
        default_interval = DEFAULT_UPLOAD_INTERVAL
    return vol.Schema(
        {
            vol.Optional(CONF_ENTITIES, default=default_entities): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class=["energy", "power"], multiple=True)
            ),
            vol.Optional(CONF_UPLOAD_INTERVAL, default=default_interval): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=opt, label=opt) for opt in INTERVAL_OPTIONS],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _smoothing_schema(entities: list[str], choices: Mapping[str, Any] | None) -> vol.Schema:
    selector = SelectSelector(
        SelectSelectorConfig(
            options=list(SMOOTHING_OPTIONS),
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="smoothing",
        )
    )
    return vol.Schema({vol.Required(entity, default=option_for(choices, entity)): selector for entity in entities})


def _smoothing_choices(entities: list[str], user_input: Mapping[str, Any]) -> dict[str, str]:
    return {entity: option_for(user_input, entity) for entity in entities}


def _describe(suggestion: list[str], skipped: dict[str, str]) -> dict[str, str]:
    lines = [f"- `{entity}`" for entity in suggestion] or ["- (keine passenden Entitäten gefunden)"]
    skipped_lines = [f"- `{entity}`: {REASONS_DE.get(reason, reason)}" for entity, reason in list(skipped.items())[:15]]
    return {
        "suggestion": "\n".join(lines),
        "skipped": "\n".join(skipped_lines) or "- keine",
    }


def _incompatible(hass: HomeAssistant, entities: list[str]) -> list[str]:
    return [
        entity
        for entity in entities
        if incompatibility(entity, (state.attributes if (state := hass.states.get(entity)) else None)) is not None
    ]


class PowermeshConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a powermesh.de account with a personal API key."""

    VERSION = 1

    def __init__(self) -> None:
        self._connection: dict[str, Any] = {}
        self._options: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the separate TLS broker and personal credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate(user_input)
            if not errors:
                await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}/{user_input[CONF_USERNAME]}")
                self._abort_if_unique_id_configured()
                self._connection = {field: user_input[field] for field in (CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD)}
                return await self.async_step_entities()
        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_entities(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Propose entities from the energy dashboard; the user may adjust them."""
        suggestion, skipped = await async_suggestion(self.hass)
        errors: dict[str, str] = {}
        placeholders = _describe(suggestion, skipped) | {"invalid": ""}
        if user_input is not None:
            selected = list(user_input.get(CONF_ENTITIES, []))
            interval = str(user_input.get(CONF_UPLOAD_INTERVAL, DEFAULT_UPLOAD_INTERVAL))
            if interval not in INTERVAL_OPTIONS:
                interval = DEFAULT_UPLOAD_INTERVAL
            if not selected:
                errors["base"] = "no_entities"
            elif invalid := _incompatible(self.hass, selected):
                errors["base"] = "incompatible"
                placeholders["invalid"] = ", ".join(invalid)
            else:
                self._options = {CONF_ENTITIES: selected, CONF_UPLOAD_INTERVAL: interval}
                return await self.async_step_smoothing()
        default_entities = list(user_input.get(CONF_ENTITIES, [])) if user_input else suggestion
        default_interval = (
            str(user_input.get(CONF_UPLOAD_INTERVAL, DEFAULT_UPLOAD_INTERVAL))
            if user_input
            else DEFAULT_UPLOAD_INTERVAL
        )
        return self.async_show_form(
            step_id="entities",
            data_schema=_entity_schema(default_entities, default_interval),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_smoothing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the smoothing per entity (default: 1 min mean)."""
        entities = self._options[CONF_ENTITIES]
        if user_input is not None:
            return self.async_create_entry(
                title="Powermesh Energie",
                data=self._connection,
                options=self._options | {CONF_SMOOTHING: _smoothing_choices(entities, user_input)},
            )
        return self.async_show_form(step_id="smoothing", data_schema=_smoothing_schema(entities, None))

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The stored key was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """New credentials do not silently authorize previously buffered data."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate(user_input)
            if not errors:
                connection = {field: user_input[field] for field in (CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD)}
                return self.async_update_reload_and_abort(
                    entry, data=connection,
                    unique_id=f"{connection[CONF_HOST]}:{connection[CONF_PORT]}/{connection[CONF_USERNAME]}",
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_connection_schema(entry.data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Allow adjusting the transferred entities later."""
        return PowermeshOptionsFlow()


class PowermeshOptionsFlow(OptionsFlow):
    """Adjust which entities are transferred, the upload interval and the smoothing."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show current selection, optionally reset to the dashboard suggestion."""
        suggestion, skipped = await async_suggestion(self.hass)
        placeholders = _describe(suggestion, skipped) | {"invalid": ""}
        errors: dict[str, str] = {}
        default_entities = list(self.config_entry.options.get(CONF_ENTITIES, []))
        default_interval = str(self.config_entry.options.get(CONF_UPLOAD_INTERVAL, DEFAULT_UPLOAD_INTERVAL))
        if default_interval not in INTERVAL_OPTIONS:
            default_interval = DEFAULT_UPLOAD_INTERVAL
        if user_input is not None:
            selected = list(user_input.get(CONF_ENTITIES, []))
            interval = str(user_input.get(CONF_UPLOAD_INTERVAL, default_interval))
            if interval not in INTERVAL_OPTIONS:
                interval = DEFAULT_UPLOAD_INTERVAL
            if user_input.get(CONF_USE_SUGGESTION):
                default_entities = suggestion
                default_interval = interval
            elif not selected:
                errors["base"] = "no_entities"
                default_entities = selected
                default_interval = interval
            elif invalid := _incompatible(self.hass, selected):
                errors["base"] = "incompatible"
                placeholders["invalid"] = ", ".join(invalid)
                default_entities = selected
                default_interval = interval
            else:
                self._options = {CONF_ENTITIES: selected, CONF_UPLOAD_INTERVAL: interval}
                return await self.async_step_smoothing()
        schema = _entity_schema(default_entities, default_interval).extend(
            {vol.Optional(CONF_USE_SUGGESTION, default=False): BooleanSelector()}
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors, description_placeholders=placeholders
        )

    async def async_step_smoothing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the smoothing per entity; new entities start with the default."""
        entities = self._options[CONF_ENTITIES]
        if user_input is not None:
            return self.async_create_entry(data=self._options | {CONF_SMOOTHING: _smoothing_choices(entities, user_input)})
        current = self.config_entry.options.get(CONF_SMOOTHING)
        return self.async_show_form(
            step_id="smoothing",
            data_schema=_smoothing_schema(entities, current if isinstance(current, dict) else None),
        )
