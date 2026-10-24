"""Config and options flow for Buttle Energie."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    ButtleAuthError,
    ButtleClient,
    ButtleConnectionError,
    ButtleError,
    ButtleForbiddenError,
    ButtleOutdatedError,
    ButtleRateLimitError,
    normalize_url,
)
from .const import API_MAJOR, CONF_ENTITIES, CONF_USE_SUGGESTION, DEFAULT_URL, DOMAIN, MIN_API_RELEASE, VERSION
from .energy_dashboard import async_suggestion
from .readings import compatibility, incompatibility, key_public_id

REASONS_DE = {
    "external_statistic": "externe Statistik, keine Entität",
    "missing": "derzeit kein Zustand",
    "entity_id": "keine sensor-Entität",
    "device_class": "Geräteklasse nicht energy/power",
    "unit": "Einheit nicht unterstützt",
    "state_class": "Zustandsklasse nicht unterstützt",
}


async def _async_validate(hass: HomeAssistant, url: str, api_key: str) -> tuple[str, dict[str, str]]:
    """Return (normalized url, errors) after checking the key against /status."""
    try:
        url = normalize_url(url)
    except ValueError as err:
        return url, {CONF_URL: str(err)}
    if key_public_id(api_key) is None:
        return url, {CONF_API_KEY: "invalid_key_format"}
    try:
        server = await ButtleClient(async_get_clientsession(hass), url, api_key).status()
    except ButtleOutdatedError:
        return url, {"base": "update_required"}
    except ButtleAuthError:
        return url, {"base": "invalid_auth"}
    except ButtleForbiddenError:
        return url, {"base": "consent_required"}
    except ButtleRateLimitError:
        return url, {"base": "rate_limited"}
    except ButtleConnectionError:
        return url, {"base": "cannot_connect"}
    except ButtleError:
        return url, {"base": "unknown"}
    problem, _ = compatibility(server, VERSION, API_MAJOR, MIN_API_RELEASE)
    return url, {"base": problem} if problem else {}


def _entity_schema(default: list[str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_ENTITIES, default=default): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class=["energy", "power"], multiple=True)
            ),
        }
    )


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


class ButtleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a buttle.de account with a personal API key."""

    VERSION = 1

    def __init__(self) -> None:
        self._url = DEFAULT_URL
        self._api_key = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for server and API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url, errors = await _async_validate(self.hass, user_input[CONF_URL], user_input[CONF_API_KEY])
            if not errors:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                self._url, self._api_key = url, user_input[CONF_API_KEY].strip()
                return await self.async_step_entities()
        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, DEFAULT_URL)): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"default_url": DEFAULT_URL},
        )

    async def async_step_entities(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Propose entities from the energy dashboard; the user may adjust them."""
        suggestion, skipped = await async_suggestion(self.hass)
        errors: dict[str, str] = {}
        placeholders = _describe(suggestion, skipped) | {"invalid": ""}
        if user_input is not None:
            selected = list(user_input.get(CONF_ENTITIES, []))
            if not selected:
                errors["base"] = "no_entities"
            elif invalid := _incompatible(self.hass, selected):
                errors["base"] = "incompatible"
                placeholders["invalid"] = ", ".join(invalid)
            else:
                return self.async_create_entry(
                    title=f"buttle.de ({self._url.split('://', 1)[1]})",
                    data={CONF_URL: self._url, CONF_API_KEY: self._api_key},
                    options={CONF_ENTITIES: selected},
                )
        default = list(user_input.get(CONF_ENTITIES, [])) if user_input else suggestion
        return self.async_show_form(
            step_id="entities",
            data_schema=_entity_schema(default),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The stored key was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a new API key."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            _, errors = await _async_validate(self.hass, entry.data[CONF_URL], user_input[CONF_API_KEY])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_API_KEY: user_input[CONF_API_KEY].strip()}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
            ),
            errors=errors,
            description_placeholders={"url": entry.data[CONF_URL]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Allow adjusting the transferred entities later."""
        return ButtleOptionsFlow()


class ButtleOptionsFlow(OptionsFlow):
    """Adjust which entities are transferred."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show current selection, optionally reset to the dashboard suggestion."""
        suggestion, skipped = await async_suggestion(self.hass)
        placeholders = _describe(suggestion, skipped) | {"invalid": ""}
        errors: dict[str, str] = {}
        default = list(self.config_entry.options.get(CONF_ENTITIES, []))
        if user_input is not None:
            selected = list(user_input.get(CONF_ENTITIES, []))
            if user_input.get(CONF_USE_SUGGESTION):
                default = suggestion
            elif not selected:
                errors["base"] = "no_entities"
                default = selected
            elif invalid := _incompatible(self.hass, selected):
                errors["base"] = "incompatible"
                placeholders["invalid"] = ", ".join(invalid)
                default = selected
            else:
                return self.async_create_entry(data={CONF_ENTITIES: selected})
        schema = _entity_schema(default).extend({vol.Optional(CONF_USE_SUGGESTION, default=False): BooleanSelector()})
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors, description_placeholders=placeholders
        )
