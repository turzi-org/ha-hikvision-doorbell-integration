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
CONF_TIMEOUT: Final = "timeout"

DEFAULT_PORT: Final = 80
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds — diagnostics poll; events are push
# HTTP request timeout. Some devices sit behind slow/high-latency links (e.g.
# an LTE router) where a plain TCP connect alone has been observed taking
# 4-6+ seconds — the previous hardcoded 10s was not enough headroom, and
# wasn't user-configurable at all. Kept generous by default and adjustable
# per device for slower links.
DEFAULT_TIMEOUT: Final = 20  # seconds
MIN_TIMEOUT: Final = 5
MAX_TIMEOUT: Final = 120

# How long the lock entity shows "unlocked" after an open pulse before
# reverting to "locked". Cosmetic approximation only — this device gives no
# ground truth (event or polled) for when the relay itself re-locks; see
# lock.py's docstring for what was checked.
DOOR_RELOCK_DELAY: Final = 3  # seconds

# Dispatcher signal (per config entry) carrying a pylocal_hikvision DeviceEvent.
SIGNAL_ACCESS_EVENT: Final = f"{DOMAIN}_access_event_{{}}"

# Home Assistant event-bus event fired for every parsed access event.
EVENT_ACCESS: Final = f"{DOMAIN}_event"

# Event labels (from pylocal_hikvision) that mean a door changed state.
DOOR_OPEN_LABELS: Final = frozenset({"door_unlocked", "door_open_normal"})
DOOR_CLOSE_LABELS: Final = frozenset({"door_locked", "door_close_normal"})
