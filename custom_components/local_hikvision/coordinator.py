# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Coordinator: diagnostics polling + the pushed alertStream event listener."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pylocal_hikvision import (
    Capabilities,
    DeviceEvent,
    DeviceInfo,
    HikvisionAuthenticationError,
    HikvisionClient,
    HikvisionError,
    UserCount,
)

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, SIGNAL_ACCESS_EVENT

_LOGGER = logging.getLogger(__name__)


@dataclass
class HikvisionData:
    """Result of a coordinator refresh."""

    device_info: DeviceInfo
    capabilities: Capabilities
    user_count: UserCount


type HikvisionConfigEntry = ConfigEntry[HikvisionCoordinator]


class HikvisionCoordinator(DataUpdateCoordinator[HikvisionData]):
    """Polls device diagnostics and runs the long-lived event stream."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HikvisionConfigEntry,
        client: HikvisionClient,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: The Home Assistant instance.
            entry: The config entry this coordinator serves.
            client: The connected :class:`HikvisionClient`.

        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            config_entry=entry,
        )
        self.client = client
        self._capabilities: Capabilities | None = None
        self._device_info: DeviceInfo | None = None
        self._listener: asyncio.Task[None] | None = None

    async def _async_update_data(self) -> HikvisionData:
        """Fetch diagnostics (device info once, capabilities once, live counts)."""
        try:
            if self._device_info is None:
                self._device_info = await self.client.get_device_info()
            if self._capabilities is None:
                self._capabilities = await self.client.get_capabilities()
            user_count = await self.client.get_user_count()
        except HikvisionAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HikvisionError as err:
            raise UpdateFailed(str(err)) from err
        return HikvisionData(
            device_info=self._device_info,
            capabilities=self._capabilities,
            user_count=user_count,
        )

    def start_event_listener(self) -> None:
        """Start the background alertStream consumer (idempotent)."""
        if self._listener is None or self._listener.done():
            self._listener = self.config_entry.async_create_background_task(
                self.hass,
                self._run_event_listener(),
                name=f"{DOMAIN}_events_{self.config_entry.entry_id}",
            )

    async def _run_event_listener(self) -> None:
        """Consume events and dispatch them to entities + the HA event bus."""
        signal = SIGNAL_ACCESS_EVENT.format(self.config_entry.entry_id)
        try:
            async for event in self.client.stream_events_reconnecting():
                _LOGGER.debug("Hikvision event: %s/%s", event.event_type, event.label)
                async_dispatcher_send(self.hass, signal, event)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let the listener crash silently
            _LOGGER.exception("Hikvision event listener stopped unexpectedly")

    async def async_shutdown(self) -> None:
        """Cancel the listener and close the client on unload."""
        if self._listener is not None:
            self._listener.cancel()
        await self.client.aclose()
        await super().async_shutdown()

    def dispatch_event(self, event: DeviceEvent) -> None:
        """Manually dispatch an event (used by tests)."""
        async_dispatcher_send(
            self.hass,
            SIGNAL_ACCESS_EVENT.format(self.config_entry.entry_id),
            event,
        )
