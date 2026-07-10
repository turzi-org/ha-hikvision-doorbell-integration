# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""The Turzi Local Hikvision integration."""

from __future__ import annotations

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from pylocal_hikvision import HikvisionClient

from .const import CONF_USE_TLS, DEFAULT_PORT, PLATFORMS
from .coordinator import HikvisionConfigEntry, HikvisionCoordinator
from .services import async_setup_services


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikvisionConfigEntry,
) -> bool:
    """Set up Turzi Local Hikvision from a config entry."""
    client = HikvisionClient(
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        use_tls=entry.data.get(CONF_USE_TLS, False),
    )
    coordinator = HikvisionCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start_event_listener()
    async_setup_services(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HikvisionConfigEntry,
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
