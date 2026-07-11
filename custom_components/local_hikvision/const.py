# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Constants for the Turzi Local Hikvision integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "local_hikvision"

PLATFORMS: Final[list[Platform]] = [
    Platform.LOCK,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
]

# Config entry keys (host/port/username/password come from homeassistant.const).
CONF_USE_TLS: Final = "use_tls"

DEFAULT_PORT: Final = 80
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds — diagnostics poll; events are push

# How long the lock entity shows "unlocked" after an open pulse before
# reverting to "locked", approximating the strike's own hold-open time (the
# device doesn't report an actual re-lock event to sync against).
DOOR_RELOCK_DELAY: Final = 5  # seconds

# Dispatcher signal (per config entry) carrying a pylocal_hikvision DeviceEvent.
SIGNAL_ACCESS_EVENT: Final = f"{DOMAIN}_access_event_{{}}"

# Home Assistant event-bus event fired for every parsed access event.
EVENT_ACCESS: Final = f"{DOMAIN}_event"

# Event labels (from pylocal_hikvision) that mean a door changed state.
DOOR_OPEN_LABELS: Final = frozenset({"door_unlocked", "door_open_normal"})
DOOR_CLOSE_LABELS: Final = frozenset({"door_locked", "door_close_normal"})
