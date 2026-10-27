"""Config and options flow for Powermesh Energie."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
    PowermeshRegistrationError,
    Registration,
    register_account,
    validate_connection,
    validate_status,
)
from .const import (
    ACCOUNT_SETUP_HOURS,
    CONF_ACCOUNT_STATUS_UNKNOWN,
    CONF_API_KEY,
    CONF_ENTITIES,
    CONF_SETUP_EXPIRES_AT,
    CONF_SMOOTHING,
    CONF_UPLOAD_INTERVAL,
    CONF_USE_SUGGESTION,
    DEFAULT_UPLOAD_INTERVAL,
    DOMAIN,
    INTERVAL_OPTIONS,
    PRIVACY_URL,
    TERMS_URL,
    WEBSITE_URL,
)
from .energy_dashboard import async_suggestion
from .readings import ENTITY_ID_PATTERN
from .smoothing import OPTIONS as SMOOTHING_OPTIONS, option_for
from .uploader import account_issue_placeholders

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_PASSWORD_CONFIRM = "password_confirm"
CONF_INVITATION_CODE = "invitation_code"
CONF_CONSENT_PRIVACY = "consent_privacy"
CONF_CONSENT_TERMS = "consent_terms"
CONF_CONSENT_STORAGE = "consent_storage"
CONSENT_FIELDS = (CONF_CONSENT_PRIVACY, CONF_CONSENT_TERMS, CONF_CONSENT_STORAGE)
EMAIL_PATTERN = re.compile(r"[^@\s]{1,64}@[^@\s]+\.[^@\s]+")
MAX_EMAIL_LENGTH = 254
MAX_PASSWORD_LENGTH = 4096
MAX_INVITATION_LENGTH = 256
REGISTRATION_ERRORS = frozenset({
    "account_exists",
    "cannot_connect",
    "invalid_registration",
    "invitation_invalid",
    "registration_rate_limited",
    "registration_rejected",
    "registration_unavailable",
    "update_required",
})

REASONS_DE = {
    "external_statistic": "externe Statistik, keine Entität",
    "missing": "derzeit kein Zustand",
    "entity_id": "keine sensor-Entität",
    "device_class": "Geräteklasse nicht Energie/Leistung",
    "unit": "Einheit nicht unterstützt",
    "state_class": "Zustandsklasse nicht unterstützt",
}


async def _async_validate(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, str]:
    """Verify the personal API key over HTTPS."""
    try:
        validate_connection(data[CONF_API_KEY])
    except (ValueError, KeyError):
        return {"base": "invalid_auth"}
    try:
        status = await PowermeshClient(
            async_get_clientsession(hass), data[CONF_API_KEY].strip()
        ).status()
        validate_status(status)
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
        vol.Required(CONF_API_KEY, default=data.get(CONF_API_KEY, "")): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    })


def _consent_schema() -> vol.Schema:
    return vol.Schema({vol.Required(field, default=False): BooleanSelector() for field in CONSENT_FIELDS})


def _account_schema(email: str) -> vol.Schema:
    # Password and invitation code are never prefilled.
    return vol.Schema({
        vol.Required(CONF_EMAIL, default=email): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="new-password")
        ),
        vol.Required(CONF_PASSWORD_CONFIRM): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="new-password")
        ),
        vol.Required(CONF_INVITATION_CODE): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="off")
        ),
    })


def _account_errors(email: str, password: Any, confirm: Any, code: str) -> dict[str, str]:
    if len(email) > MAX_EMAIL_LENGTH or EMAIL_PATTERN.fullmatch(email) is None:
        return {CONF_EMAIL: "invalid_email"}
    if not isinstance(password, str) or not password or len(password) > MAX_PASSWORD_LENGTH:
        return {CONF_PASSWORD: "password_required"}
    if password != confirm:
        return {CONF_PASSWORD_CONFIRM: "password_mismatch"}
    if not code or len(code) > MAX_INVITATION_LENGTH:
        return {CONF_INVITATION_CODE: "invitation_required"}
    return {}


def _entity_schema(default_entities: list[str], default_interval: str = DEFAULT_UPLOAD_INTERVAL) -> vol.Schema:
    if default_interval not in INTERVAL_OPTIONS:
        default_interval = DEFAULT_UPLOAD_INTERVAL
    return vol.Schema(
        {
            vol.Optional(CONF_ENTITIES, default=default_entities): EntitySelector(
                EntitySelectorConfig(domain="sensor", multiple=True)
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
        if not isinstance(entity, str) or not ENTITY_ID_PATTERN.fullmatch(entity)
    ]


class PowermeshConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up powermesh.de with a personal API key or a new invited account."""

    VERSION = 1

    def __init__(self) -> None:
        self._connection: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._registering = False
        self._registration_in_progress = False
        self._registration_sent = False

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose between an existing API key and a new account."""
        return self.async_show_menu(step_id="user", menu_options=["api_key", "register"])

    async def async_step_api_key(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a personal API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate(self.hass, user_input)
            if not errors:
                api_key = user_input[CONF_API_KEY].strip()
                await self.async_set_unique_id(api_key.split("_", 2)[1])
                self._abort_if_unique_id_configured()
                self._connection = {CONF_API_KEY: api_key}
                return await self.async_step_entities()
        return self.async_show_form(
            step_id="api_key",
            data_schema=_connection_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_register(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Separate, explicit confirmations before a new account is requested."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = {field: "consent_missing" for field in CONSENT_FIELDS if user_input.get(field) is not True}
            if not errors:
                self._registering = True
                return await self.async_step_entities()
        return self.async_show_form(
            step_id="register",
            data_schema=_consent_schema(),
            errors=errors,
            description_placeholders={
                "privacy_url": PRIVACY_URL,
                "terms_url": TERMS_URL,
                "hours": str(ACCOUNT_SETUP_HOURS),
            },
        )

    async def async_step_register_account(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Send the single registration request and keep the issued key at once."""
        if self._registration_sent:
            return self.async_abort(reason="registration_uncertain")
        if not self._registering or CONF_SMOOTHING not in self._options:
            return self.async_abort(reason="registration_incomplete")
        errors: dict[str, str] = {}
        email = ""
        if user_input is not None:
            email = str(user_input.get(CONF_EMAIL, "")).strip()
            code = str(user_input.get(CONF_INVITATION_CODE, "")).strip()
            errors = _account_errors(
                email, user_input.get(CONF_PASSWORD), user_input.get(CONF_PASSWORD_CONFIRM), code
            )
            if not errors and self._registration_in_progress:
                errors = {"base": "registration_in_progress"}
            if not errors:
                self._registration_in_progress = True
                try:
                    registration = await register_account(
                        async_get_clientsession(self.hass),
                        email=email,
                        password=user_input[CONF_PASSWORD],
                        invitation_code=code,
                    )
                except PowermeshRegistrationError as err:
                    if err.uncertain:
                        self._registration_sent = True
                        return self.async_abort(reason="registration_uncertain")
                    errors = {"base": err.code if err.code in REGISTRATION_ERRORS else "registration_rejected"}
                except Exception:  # noqa: BLE001 - never resubmit after an unknown outcome
                    self._registration_sent = True
                    return self.async_abort(reason="registration_uncertain")
                else:
                    self._registration_sent = True
                    return await self._async_create_registered_entry(registration)
                finally:
                    self._registration_in_progress = False
        return self.async_show_form(
            step_id="register_account",
            data_schema=_account_schema(email),
            errors=errors,
            description_placeholders={"url": WEBSITE_URL, "hours": str(ACCOUNT_SETUP_HOURS)},
        )

    async def _async_create_registered_entry(self, registration: Registration) -> ConfigFlowResult:
        account = registration.account
        await self.async_set_unique_id(registration.api_key.split("_", 2)[1], raise_on_progress=False)
        data: dict[str, Any] = {CONF_API_KEY: registration.api_key}
        if account is None:
            # Protocol error: keep the one-time key, report it, never invent a deadline.
            data[CONF_ACCOUNT_STATUS_UNKNOWN] = True
            return self.async_create_entry(
                title="Powermesh Energie",
                data=data,
                options=self._options,
                description="account_status_unknown",
                description_placeholders={"url": WEBSITE_URL, "hours": str(ACCOUNT_SETUP_HOURS)},
            )
        if account.setup_required and account.setup_expires_at is not None:
            data[CONF_SETUP_EXPIRES_AT] = account.setup_expires_at
        return self.async_create_entry(
            title="Powermesh Energie",
            data=data,
            options=self._options,
            description="account_setup_required" if account.setup_required else None,
            description_placeholders=account_issue_placeholders(account),
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
        if user_input is not None and self._registering:
            self._options = self._options | {CONF_SMOOTHING: _smoothing_choices(entities, user_input)}
            return await self.async_step_register_account()
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
            errors = await _async_validate(self.hass, user_input)
            if not errors:
                api_key = user_input[CONF_API_KEY].strip()
                connection = {CONF_API_KEY: api_key}
                return self.async_update_reload_and_abort(
                    entry, data=connection,
                    unique_id=api_key.split("_", 2)[1],
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
