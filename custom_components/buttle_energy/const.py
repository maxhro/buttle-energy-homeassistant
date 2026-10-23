"""Constants for the Buttle Energie integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "buttle_energy"
# Keep in sync with manifest.json.
VERSION: Final = "0.2.0"
API_MAJOR: Final = 1
MIN_API_RELEASE: Final = "1.1.0"
CLIENT_ID: Final = f"homeassistant/{VERSION}"
DEFAULT_URL: Final = "https://buttle.de"

CONF_ENTITIES: Final = "entities"
CONF_USE_SUGGESTION: Final = "use_dashboard_suggestion"

UPLOAD_INTERVAL: Final = timedelta(minutes=5)
MAX_READINGS_PER_REQUEST: Final = 200
# Upper bound for the offline buffer; the oldest readings are dropped beyond it.
MAX_BUFFERED_READINGS: Final = 20_000
STORAGE_VERSION: Final = 1
REQUEST_TIMEOUT_SECONDS: Final = 30

STATUS_OK: Final = "ok"
STATUS_PENDING: Final = "pending"
STATUS_OFFLINE: Final = "offline"
STATUS_RATE_LIMITED: Final = "rate_limited"
STATUS_AUTH_FAILED: Final = "auth_failed"
STATUS_CONSENT_REQUIRED: Final = "consent_required"
STATUS_REJECTED: Final = "rejected"
STATUS_UPDATE_REQUIRED: Final = "update_required"
STATUS_API_INCOMPATIBLE: Final = "api_incompatible"
STATUSES: Final = [
    STATUS_PENDING,
    STATUS_OK,
    STATUS_OFFLINE,
    STATUS_RATE_LIMITED,
    STATUS_AUTH_FAILED,
    STATUS_CONSENT_REQUIRED,
    STATUS_REJECTED,
    STATUS_UPDATE_REQUIRED,
    STATUS_API_INCOMPATIBLE,
]
