"""Collects state changes, buffers them persistently and uploads them in batches."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta
import logging
import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import (
    AccountState,
    PowermeshAuthError,
    PowermeshClient,
    PowermeshConnectionError,
    PowermeshError,
    PowermeshForbiddenError,
    PowermeshOutdatedError,
    PowermeshRateLimitError,
    PowermeshRejectedError,
    encode_request,
    parse_account,
    parse_buffer_limit,
    validate_status,
)
from .const import (
    API_MAJOR,
    CONF_ENTITIES,
    CONF_ACCOUNT_STATUS_UNKNOWN,
    CONF_SETUP_EXPIRES_AT,
    CONF_SMOOTHING,
    CONF_UPLOAD_INTERVAL,
    DEFAULT_UPLOAD_INTERVAL,
    DOMAIN,
    INTERVAL_MAP,
    INTERVAL_OPTIONS,
    MAX_READINGS_PER_REQUEST,
    MIN_API_RELEASE,
    STATUS_API_INCOMPATIBLE,
    STATUS_BUFFER_FULL,
    STATUS_LIMITS_UNKNOWN,
    STATUS_AUTH_FAILED,
    STATUS_CONSENT_REQUIRED,
    STATUS_OFFLINE,
    STATUS_OK,
    STATUS_PENDING,
    STATUS_RATE_LIMITED,
    STATUS_REJECTED,
    STATUS_UPDATE_REQUIRED,
    REST_BUFFER_FORMAT,
    STORAGE_VERSION,
    UPLOAD_INTERVAL,
    VERSION,
    WEBSITE_URL,
)
from .metadata import entity_friendly_name, entity_metadata
from .readings import build_reading, compatibility, is_api_reading
from .smoothing import Smoother, option_for

_LOGGER = logging.getLogger(__name__)
# How often finished smoothing windows are checked; shorter than the smallest window.
SMOOTHING_TICK = timedelta(seconds=5)
ISSUE_ACCOUNT_SETUP = "account_setup_required"
ISSUE_ACCOUNT_EXPIRED = "account_setup_expired"
ISSUE_ACCOUNT_UNKNOWN = "account_status_unknown"
ACCOUNT_ISSUES = (ISSUE_ACCOUNT_SETUP, ISSUE_ACCOUNT_EXPIRED, ISSUE_ACCOUNT_UNKNOWN)


def format_deadline(expires_at: int | None) -> str:
    """Local, human-readable setup deadline."""
    if expires_at is None:
        return "?"
    try:
        moment = dt_util.as_local(dt_util.utc_from_timestamp(expires_at))
    except (OverflowError, OSError, ValueError):
        return "?"
    return moment.strftime("%d.%m.%Y %H:%M %Z").strip()


def account_issue_placeholders(account: AccountState | None) -> dict[str, str]:
    """Translation placeholders for setup warnings; never credentials."""
    return {
        "deadline": format_deadline(account.setup_expires_at if account else None),
        "warning": (account.warning or "") if account else "",
        "url": WEBSITE_URL,
    }


class PowermeshUploader:
    """Owns the reading buffer and the upload schedule of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: PowermeshClient) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.entities: list[str] = list(entry.options.get(CONF_ENTITIES, []))
        choices = entry.options.get(CONF_SMOOTHING)
        self.smoothing: dict[str, str] = {
            entity_id: option_for(choices if isinstance(choices, dict) else None, entity_id)
            for entity_id in self.entities
        }
        self._smoothers = {entity_id: Smoother(option) for entity_id, option in self.smoothing.items()}
        self.status = STATUS_PENDING
        self.last_upload: datetime | None = None
        self.last_error: str | None = None
        self.accepted_total = 0
        self.dropped_total = 0
        self.server_release: str | None = None
        self.latest_version: str | None = None
        self._buffer: list[dict[str, Any]] = []
        self._index: dict[tuple[str, str], int] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.buffer", private=True
        )
        self._unsubscribers: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []
        self._retry_at: datetime | None = None
        self._paused = False
        self._legacy_buffer: dict[str, Any] | None = None
        self._blocked_buffer_count = 0
        self._uploading = False
        self._buffer_owner: str | None = None
        self._inflight: dict[str, Any] | None = None
        self._stopping = False
        self._upload_task: Any = None
        self._active_upload: asyncio.Task[Any] | None = None
        self.account: AccountState | None = None
        self.buffer_limit: int | None = None
        self._buffer_error: str | None = None

    @property
    def pending(self) -> int:
        """Number of readings waiting for upload."""
        return (
            len(self._buffer)
            + len(self._inflight["readings"] if self._inflight else [])
            + self._blocked_buffer_count
        )

    @property
    def interval_name(self) -> str:
        """Configured upload interval key (e.g. '5min')."""
        choice = str(self.entry.options.get(CONF_UPLOAD_INTERVAL, DEFAULT_UPLOAD_INTERVAL))
        return choice if choice in INTERVAL_OPTIONS else DEFAULT_UPLOAD_INTERVAL

    @property
    def interval(self) -> timedelta:
        """Configured upload interval as timedelta."""
        return INTERVAL_MAP[self.interval_name]

    async def async_start(self) -> None:
        """Restore the buffer, record current values and start listening."""
        stored = await self._store.async_load()
        self.account = self._initial_account(stored)
        self._refresh_account_issue()
        if stored:
            readings = stored.get("readings", [])
            inflight = stored.get("inflight")
            all_readings = list(readings) if isinstance(readings, list) else []
            if isinstance(inflight, dict):
                inflight_readings = inflight.get("readings")
                if isinstance(inflight_readings, list):
                    all_readings.extend(inflight_readings)
                elif inflight:
                    all_readings.append(inflight)
            elif inflight is not None:
                all_readings.append(inflight)
            incompatible = (
                (stored.get("transport") != REST_BUFFER_FORMAT and bool(all_readings))
                or any(not is_api_reading(reading) for reading in all_readings)
            )
            if incompatible:
                self._legacy_buffer = deepcopy(stored)
                self._blocked_buffer_count = len(all_readings)
                self._block(STATUS_REJECTED, "incompatible_local_buffer")
                return
            if not isinstance(readings, list):
                self._legacy_buffer = deepcopy(stored)
                self._blocked_buffer_count = len(all_readings)
                self._block(STATUS_REJECTED, "invalid_local_buffer")
                return
            self._buffer_owner = stored.get("owner")
            if self._buffer_owner == self.client.key_id:
                try:
                    self.buffer_limit = parse_buffer_limit(stored.get("limits"))
                except PowermeshOutdatedError:
                    self._buffer_problem(STATUS_LIMITS_UNKNOWN)
            self.dropped_total = (
                stored["dropped_total"]
                if type(stored.get("dropped_total")) is int and stored["dropped_total"] >= 0
                else 0
            )
            if stored.get("buffer_error") in (STATUS_BUFFER_FULL, STATUS_LIMITS_UNKNOWN):
                self._buffer_problem(stored["buffer_error"])
            self._inflight = inflight
            if self._inflight is not None and (
                not isinstance(self._inflight, dict)
                or not isinstance(self._inflight.get("readings"), list)
                or not 1 <= len(self._inflight["readings"]) <= MAX_READINGS_PER_REQUEST
                or not all(is_api_reading(item) for item in self._inflight["readings"])
            ):
                self._legacy_buffer = deepcopy(stored)
                self._blocked_buffer_count = len(all_readings)
                self._block(STATUS_REJECTED, "invalid_local_buffer")
                return
            # Existing data must survive upgrades and server-side limit reductions.
            self._replace_buffer([
                reading for reading in readings if reading.get("entity_id") in self.entities
            ])
        await self.async_check_version()
        if self._paused:
            return
        for entity_id in self.entities:
            if (state := self.hass.states.get(entity_id)) is not None:
                self._record(entity_id, state.state, state.attributes, state.last_updated)
        if self.entities:
            self._unsubscribers.append(
                async_track_state_change_event(self.hass, self.entities, self._handle_state_change)
            )
        self._unsubscribers.append(
            async_track_time_interval(self.hass, self._handle_interval, self.interval)
        )
        self._unsubscribers.append(
            async_track_time_interval(self.hass, self._handle_tick, SMOOTHING_TICK)
        )
        self._unsubscribers.append(
            self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, self._handle_stop)
        )
        self._upload_task = self.entry.async_create_background_task(
            self.hass, self._async_initial(), f"{DOMAIN} initial upload"
        )

    async def _async_initial(self) -> None:
        await self.async_upload()

    def _initial_account(self, stored: Any) -> AccountState | None:
        saved = AccountState.from_dict(stored.get("account")) if isinstance(stored, dict) else None
        if saved is not None:
            return saved
        seed = self.entry.data.get(CONF_SETUP_EXPIRES_AT)
        if type(seed) is int and seed > 0:
            return AccountState(True, seed)
        if self.entry.data.get(CONF_ACCOUNT_STATUS_UNKNOWN) is True:
            return AccountState(True)
        return None

    @callback
    def _apply_account(self, account: AccountState | None) -> None:
        """Take over a server-reported setup status; absent status changes nothing."""
        if account is None:
            return
        changed = account != self.account
        self.account = account
        self._refresh_account_issue()
        if changed and self._legacy_buffer is None:
            self._store.async_delay_save(self._data, 1)

    @callback
    def _refresh_account_issue(self) -> None:
        """Keep the setup warning visible until the server confirms completion."""
        account = self.account
        if account is None:
            return
        issue = None
        if account.setup_required:
            expires = account.setup_expires_at
            if expires is None:
                issue = ISSUE_ACCOUNT_UNKNOWN
            elif dt_util.utcnow().timestamp() >= expires:
                # An expired key gets an ordinary auth error; the stored server
                # deadline explains it.
                issue = ISSUE_ACCOUNT_EXPIRED
            else:
                issue = ISSUE_ACCOUNT_SETUP
        for other in ACCOUNT_ISSUES:
            if other != issue:
                ir.async_delete_issue(self.hass, DOMAIN, f"{other}_{self.entry.entry_id}")
        if issue is None:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{issue}_{self.entry.entry_id}",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR if issue == ISSUE_ACCOUNT_EXPIRED else ir.IssueSeverity.WARNING,
            translation_key=issue,
            translation_placeholders=account_issue_placeholders(account),
        )

    @callback
    def _account_auth_failed(self, err: PowermeshAuthError) -> None:
        # No dedicated expiry code exists; re-evaluate the remembered server deadline.
        self._refresh_account_issue()

    async def async_check_version(self) -> bool:
        """Compare versions with the server; pause on incompatibility."""
        try:
            server = await self.client.status()
        except PowermeshOutdatedError as err:
            self._block(STATUS_UPDATE_REQUIRED, err.code)
            return False
        except PowermeshAuthError as err:
            self._paused = True
            self._set_error(STATUS_AUTH_FAILED, err.code)
            self._account_auth_failed(err)
            self.entry.async_start_reauth(self.hass)
            self._notify()
            return False
        except PowermeshRateLimitError as err:
            self._retry_at = dt_util.utcnow() + timedelta(seconds=max(1, min(err.retry_after, 3600)) + random.uniform(0, 5))
            self._set_error(STATUS_RATE_LIMITED, err.code)
            return False
        except PowermeshForbiddenError as err:
            self._set_error(STATUS_CONSENT_REQUIRED, err.code)
            return False
        except PowermeshError as err:
            self._set_error(STATUS_OFFLINE, err.code)
            if self.buffer_limit is None:
                self._buffer_problem(STATUS_LIMITS_UNKNOWN)
            return False
        try:
            validate_status(server)
        except PowermeshOutdatedError as err:
            self._block(STATUS_API_INCOMPATIBLE, err.code)
            return False
        self._apply_account(parse_account(server))
        self.server_release = server.get("api_release") if isinstance(server.get("api_release"), str) else None
        problem, latest = compatibility(server, VERSION, API_MAJOR, MIN_API_RELEASE)
        if problem is not None:
            self._block(
                STATUS_UPDATE_REQUIRED if problem == "update_required" else STATUS_API_INCOMPATIBLE,
                problem,
            )
            return False
        if self.pending and self._buffer_owner not in (None, self.client.key_id):
            self._block(STATUS_REJECTED, "buffer_owner_changed")
            return False
        first_buffer = not self.pending
        self.buffer_limit = parse_buffer_limit(server["limits"])
        self._buffer_owner = self.client.key_id
        if self.pending > self.buffer_limit:
            self._buffer_problem(STATUS_BUFFER_FULL)
        self.latest_version = latest if latest != VERSION else None
        await self._store.async_save(self._data())
        if first_buffer:
            for entity_id in self.entities:
                if (state := self.hass.states.get(entity_id)) is not None:
                    self._record(entity_id, state.state, state.attributes, state.last_updated)
        for issue in ("update_required", "api_incompatible", "buffer_incompatible", "buffer_owner_changed", "invalid_local_buffer"):
            ir.async_delete_issue(self.hass, DOMAIN, f"{issue}_{self.entry.entry_id}")
        if latest is not None:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"update_available_{self.entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="update_available",
                translation_placeholders={"installed": VERSION, "latest": latest},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, f"update_available_{self.entry.entry_id}")
        self._notify()
        return True

    def _block(self, status: str, code: str) -> None:
        self._paused = True
        self._set_error(status, code)
        if status == STATUS_REJECTED:
            issue = (
                "buffer_incompatible" if code == "incompatible_local_buffer"
                else "buffer_owner_changed" if code == "buffer_owner_changed"
                else "invalid_local_buffer"
            )
        else:
            issue = "update_required" if status == STATUS_UPDATE_REQUIRED else "api_incompatible"
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{issue}_{self.entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=issue,
            translation_placeholders={"installed": VERSION, "server": self.server_release or "?"},
        )
        self._notify()

    async def async_stop(self) -> None:
        """Stop listening and persist the buffer."""
        self._stopping = True
        if self._upload_task is not None and not self._upload_task.done():
            self._upload_task.cancel()
            try:
                await self._upload_task
            except asyncio.CancelledError:
                pass
        if self._active_upload is not None and not self._active_upload.done():
            self._active_upload.cancel()
            try:
                await self._active_upload
            except asyncio.CancelledError:
                pass
        while self._unsubscribers:
            self._unsubscribers.pop()()
        if self._legacy_buffer is None:
            self._drain()
            await self._store.async_save(self._data())

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Register a callback for status changes (used by the sensors)."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _data(self) -> dict[str, Any]:
        return deepcopy({
            "transport": REST_BUFFER_FORMAT,
            "readings": self._buffer,
            "owner": self._buffer_owner,
            "inflight": self._inflight,
            "account": self.account.as_dict() if self.account else None,
            "limits": {"buffer_limit_readings": self.buffer_limit},
            "buffer_error": self._buffer_error,
            "dropped_total": self.dropped_total,
        })

    @callback
    def _append(self, reading: dict[str, Any]) -> None:
        # Newer values within the same second replace older ones.
        key = (reading["entity_id"], reading["timestamp"])
        if self.buffer_limit is not None and (position := self._index.get(key)) is not None:
            self._buffer[position] = reading
            return
        if self.buffer_limit is None or self.pending >= self.buffer_limit:
            self.dropped_total += 1
            self._buffer_problem(
                STATUS_LIMITS_UNKNOWN if self.buffer_limit is None else STATUS_BUFFER_FULL
            )
            _LOGGER.error(
                "Discarded new reading: %s (pending=%s, limit=%s, dropped_total=%s)",
                self._buffer_error, self.pending, self.buffer_limit, self.dropped_total,
            )
            return
        self._index[key] = len(self._buffer)
        self._buffer.append(reading)

    @callback
    def _buffer_problem(self, code: str) -> None:
        self._buffer_error = code
        self._set_error(code, code)
        ir.async_create_issue(
            self.hass, DOMAIN, f"buffer_limit_{self.entry.entry_id}",
            is_fixable=False, is_persistent=True, severity=ir.IssueSeverity.ERROR,
            translation_key="buffer_limit",
        )
        self._notify()

    def _clear_buffer_problem(self) -> None:
        if self.buffer_limit is not None and self.pending < self.buffer_limit:
            self._buffer_error = None
            ir.async_delete_issue(self.hass, DOMAIN, f"buffer_limit_{self.entry.entry_id}")

    def _replace_buffer(self, readings: list[dict[str, Any]]) -> None:
        self._buffer = readings
        self._index = {(r["entity_id"], r["timestamp"]): i for i, r in enumerate(readings)}

    @callback
    def _record(self, entity_id: str, state: str, attributes: Any, when: datetime) -> None:
        safe_attributes = dict(attributes)
        friendly_name = safe_attributes.get("friendly_name")
        if (
            not isinstance(friendly_name, str)
            or not friendly_name
            or friendly_name.casefold() in {"unknown", "unavailable", "none"}
        ):
            safe_attributes["friendly_name"] = entity_friendly_name(self.hass, entity_id)
        reading = build_reading(
            entity_id, state, safe_attributes, when, entity_metadata(self.hass, entity_id)
        )
        smoother = self._smoothers.get(entity_id)
        if reading is None or smoother is None or self._paused:
            return
        if self._buffer_owner is None or self.buffer_limit is None:
            self._enqueue([reading])
            return
        self._enqueue(smoother.add(reading, when))

    @callback
    def _enqueue(self, readings: list[dict[str, Any]]) -> None:
        if not readings:
            return
        for reading in readings:
            self._append(reading)
        self._store.async_delay_save(self._data, 30)
        self._notify()

    @callback
    def _flush_windows(self, now: datetime) -> None:
        for smoother in self._smoothers.values():
            self._enqueue(smoother.flush(now))

    @callback
    def _drain(self) -> None:
        now = dt_util.utcnow()
        for smoother in self._smoothers.values():
            for reading in smoother.drain(now):
                self._append(reading)

    @callback
    def _handle_tick(self, now: datetime) -> None:
        self._flush_windows(now)

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is not None:
            self._record(new_state.entity_id, new_state.state, new_state.attributes, new_state.last_updated)

    async def _handle_interval(self, _now: datetime) -> None:
        if self.account is not None and self.account.setup_required:
            self._refresh_account_issue()
        await self.async_upload()

    async def _handle_stop(self, _event: Event) -> None:
        await self.async_stop()

    async def async_upload(self) -> None:
        """Send buffered readings in batches until done or an error stops us."""
        self._flush_windows(dt_util.utcnow())
        if self._uploading or self._paused or self._stopping:
            return
        if self._retry_at is not None and dt_util.utcnow() < self._retry_at:
            return
        if not self.pending:
            if self._buffer_owner is None or self.buffer_limit is None:
                await self.async_check_version()
            if not self.pending and self.status == STATUS_PENDING:
                self.status = STATUS_OK
                self._notify()
            if not self.pending:
                return
        self._uploading = True
        self._active_upload = asyncio.current_task()
        try:
            if not await self.async_check_version():
                return
            await self._upload_batches()
        finally:
            self._uploading = False
            self._active_upload = None
            await self._store.async_save(self._data())
            self._notify()

    async def _upload_batches(self) -> None:
        while self.pending and not self._stopping:
            if self._inflight is None:
                batch = deepcopy(self._buffer[:MAX_READINGS_PER_REQUEST])
                request = {"readings": batch}
                while True:
                    try:
                        encode_request(request)
                        break
                    except PowermeshRejectedError:
                        if len(batch) <= 1:
                            self._block(STATUS_REJECTED, "invalid_local_buffer")
                            return
                        batch = batch[:len(batch) // 2]
                        request["readings"] = batch
                self._inflight = {"readings": batch}
                self._replace_buffer(self._buffer[len(batch):])
            batch = self._inflight["readings"]
            await self._store.async_save(self._data())
            try:
                result = await self.client.upload(batch)
            except PowermeshConnectionError as err:
                self._retry_at = dt_util.utcnow() + timedelta(seconds=30 + random.uniform(0, 10))
                self._set_error(STATUS_OFFLINE, err.code)
                return
            except PowermeshRateLimitError as err:
                self._retry_at = dt_util.utcnow() + timedelta(seconds=max(1, min(err.retry_after, 3600)) + random.uniform(0, 5))
                self._set_error(STATUS_RATE_LIMITED, err.code)
                return
            except PowermeshOutdatedError as err:
                self._block(STATUS_UPDATE_REQUIRED, err.code)
                return
            except PowermeshAuthError as err:
                self._paused = True
                self._set_error(STATUS_AUTH_FAILED, err.code)
                self._account_auth_failed(err)
                self.entry.async_start_reauth(self.hass)
                return
            except PowermeshForbiddenError as err:
                self._set_error(STATUS_CONSENT_REQUIRED, err.code)
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"consent_{self.entry.entry_id}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="consent_required",
                    translation_placeholders={"url": self.client.base_url},
                )
                return
            except PowermeshRejectedError as err:
                self._block(STATUS_REJECTED, err.code)
                return
            self._inflight = None
            self._apply_account(result.account)
            self._clear_buffer_problem()
            await self._store.async_save(self._data())
            self.accepted_total += result.accepted
            self.last_upload = dt_util.utcnow()
            self.last_error = self._buffer_error
            self.status = self._buffer_error or STATUS_OK
            self._retry_at = None
            ir.async_delete_issue(self.hass, DOMAIN, f"consent_{self.entry.entry_id}")
            if result.remaining_requests == 0:
                return

    def _set_error(self, status: str, code: str) -> None:
        if self._buffer_error and status in (STATUS_OFFLINE, STATUS_RATE_LIMITED):
            status = code = self._buffer_error
        self.status = status
        self.last_error = code
        _LOGGER.debug("Upload stopped: %s (%s)", status, code)
