"""Collects state changes, buffers them persistently and uploads them in batches."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import (
    ButtleAuthError,
    ButtleClient,
    ButtleConnectionError,
    ButtleError,
    ButtleForbiddenError,
    ButtleOutdatedError,
    ButtleRateLimitError,
    ButtleRejectedError,
)
from .const import (
    API_MAJOR,
    CONF_ENTITIES,
    DOMAIN,
    MAX_BUFFERED_READINGS,
    MAX_READINGS_PER_REQUEST,
    MIN_API_RELEASE,
    STATUS_API_INCOMPATIBLE,
    STATUS_AUTH_FAILED,
    STATUS_CONSENT_REQUIRED,
    STATUS_OFFLINE,
    STATUS_OK,
    STATUS_PENDING,
    STATUS_RATE_LIMITED,
    STATUS_REJECTED,
    STATUS_UPDATE_REQUIRED,
    STORAGE_VERSION,
    UPLOAD_INTERVAL,
    VERSION,
)
from .readings import build_reading, compatibility, invalid_indices

_LOGGER = logging.getLogger(__name__)


class ButtleUploader:
    """Owns the reading buffer and the upload schedule of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: ButtleClient) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.entities: list[str] = list(entry.options.get(CONF_ENTITIES, []))
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
        self._uploading = False

    @property
    def pending(self) -> int:
        """Number of readings waiting for upload."""
        return len(self._buffer)

    async def async_start(self) -> None:
        """Restore the buffer, record current values and start listening."""
        stored = await self._store.async_load()
        for reading in (stored or {}).get("readings", []):
            if isinstance(reading, dict) and reading.get("entity_id") in self.entities:
                self._append(reading)
        for entity_id in self.entities:
            if (state := self.hass.states.get(entity_id)) is not None:
                self._record(entity_id, state.state, state.attributes, state.last_updated)
        if self.entities:
            self._unsubscribers.append(
                async_track_state_change_event(self.hass, self.entities, self._handle_state_change)
            )
        self._unsubscribers.append(
            async_track_time_interval(self.hass, self._handle_interval, UPLOAD_INTERVAL)
        )
        self._unsubscribers.append(
            self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, self._handle_stop)
        )
        self.entry.async_create_background_task(
            self.hass, self._async_initial(), f"{DOMAIN} initial upload"
        )

    async def _async_initial(self) -> None:
        await self.async_check_version()
        await self.async_upload()

    async def async_check_version(self) -> None:
        """Compare versions with the server; pause on incompatibility."""
        try:
            server = await self.client.status()
        except ButtleOutdatedError as err:
            self._block(STATUS_UPDATE_REQUIRED, err.code)
            return
        except ButtleAuthError as err:
            self._paused = True
            self._set_error(STATUS_AUTH_FAILED, err.code)
            self.entry.async_start_reauth(self.hass)
            self._notify()
            return
        except ButtleError:
            # Connection, consent or throttling problems surface during upload.
            return
        self.server_release = server.get("api_release") if isinstance(server.get("api_release"), str) else None
        problem, latest = compatibility(server, VERSION, API_MAJOR, MIN_API_RELEASE)
        self.latest_version = latest
        if problem is not None:
            self._block(STATUS_UPDATE_REQUIRED if problem == "update_required" else STATUS_API_INCOMPATIBLE, problem)
            return
        for issue in ("update_required", "api_incompatible"):
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

    def _block(self, status: str, code: str) -> None:
        self._paused = True
        self._set_error(status, code)
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
        while self._unsubscribers:
            self._unsubscribers.pop()()
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
        return {"readings": self._buffer}

    @callback
    def _append(self, reading: dict[str, Any]) -> None:
        # Newer values within the same second replace older ones.
        key = (reading["entity_id"], reading["timestamp"])
        if (position := self._index.get(key)) is not None:
            self._buffer[position] = reading
            return
        self._index[key] = len(self._buffer)
        self._buffer.append(reading)
        if len(self._buffer) > MAX_BUFFERED_READINGS:
            overflow = len(self._buffer) - MAX_BUFFERED_READINGS
            self._replace_buffer(self._buffer[overflow:])
            self.dropped_total += overflow
            _LOGGER.warning("Offline buffer full; dropped %s oldest readings", overflow)

    def _replace_buffer(self, readings: list[dict[str, Any]]) -> None:
        self._buffer = readings
        self._index = {(r["entity_id"], r["timestamp"]): i for i, r in enumerate(readings)}

    @callback
    def _record(self, entity_id: str, state: str, attributes: Any, when: datetime) -> None:
        reading = build_reading(entity_id, state, attributes, when)
        if reading is None:
            return
        self._append(reading)
        self._store.async_delay_save(self._data, 30)
        self._notify()

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is not None:
            self._record(new_state.entity_id, new_state.state, new_state.attributes, new_state.last_updated)

    async def _handle_interval(self, _now: datetime) -> None:
        await self.async_upload()

    async def _handle_stop(self, _event: Event) -> None:
        await self._store.async_save(self._data())

    async def async_upload(self) -> None:
        """Send buffered readings in batches until done or an error stops us."""
        if self._uploading or self._paused or not self._buffer:
            if not self._buffer and self.status == STATUS_PENDING:
                self.status = STATUS_OK
                self._notify()
            return
        if self._retry_at is not None and dt_util.utcnow() < self._retry_at:
            return
        self._uploading = True
        try:
            await self._upload_batches()
        finally:
            self._uploading = False
            await self._store.async_save(self._data())
            self._notify()

    async def _upload_batches(self) -> None:
        while self._buffer:
            batch = self._buffer[:MAX_READINGS_PER_REQUEST]
            try:
                result = await self.client.upload(batch)
            except ButtleConnectionError as err:
                self._set_error(STATUS_OFFLINE, err.code)
                return
            except ButtleRateLimitError as err:
                self._retry_at = dt_util.utcnow() + timedelta(seconds=max(1, min(err.retry_after, 3600)))
                self._set_error(STATUS_RATE_LIMITED, err.code)
                return
            except ButtleOutdatedError as err:
                self._block(STATUS_UPDATE_REQUIRED, err.code)
                return
            except ButtleAuthError as err:
                self._paused = True
                self._set_error(STATUS_AUTH_FAILED, err.code)
                self.entry.async_start_reauth(self.hass)
                return
            except ButtleForbiddenError as err:
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
            except ButtleRejectedError as err:
                rejected = invalid_indices(err.body)
                if not rejected:
                    # Unknown rejection of the whole batch: drop it so it cannot block later data.
                    rejected = set(range(len(batch)))
                _LOGGER.warning(
                    "buttle.de rejected %s of %s readings (%s); they are discarded",
                    len(rejected), len(batch), err.code,
                )
                self.dropped_total += len(rejected)
                kept = [reading for i, reading in enumerate(batch) if i not in rejected]
                self._replace_buffer(kept + self._buffer[len(batch):])
                self._set_error(STATUS_REJECTED, err.code)
                continue
            self._replace_buffer(self._buffer[len(batch):])
            self.accepted_total += result.accepted
            self.last_upload = dt_util.utcnow()
            self.last_error = None
            self.status = STATUS_OK
            self._retry_at = None
            ir.async_delete_issue(self.hass, DOMAIN, f"consent_{self.entry.entry_id}")
            if result.remaining_requests == 0:
                return

    def _set_error(self, status: str, code: str) -> None:
        self.status = status
        self.last_error = code
        _LOGGER.debug("Upload stopped: %s (%s)", status, code)

