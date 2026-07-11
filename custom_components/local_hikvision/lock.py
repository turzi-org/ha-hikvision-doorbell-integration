# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Lock entities — one per door relay (momentary open)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOOR_CLOSE_LABELS, DOOR_OPEN_LABELS, SIGNAL_ACCESS_EVENT
from .coordinator import HikvisionConfigEntry, HikvisionCoordinator
from .entity import HikvisionEntity
from .isapi import DeviceEvent


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikvisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one lock per door reported by the device capabilities."""
    coordinator = entry.runtime_data
    door_count = coordinator.data.capabilities.door_count or 1
    async_add_entities(
        HikvisionDoorLock(coordinator, door_no)
        for door_no in range(1, door_count + 1)
    )


class HikvisionDoorLock(HikvisionEntity, LockEntity):
    """A door relay exposed as a lock supporting the momentary open action.

    The device reports its own door state transitions over the alertStream
    (the same feed the door-contact binary_sensor uses); this entity's
    "locked"/"unlocked" state is driven by those pushed events, not by a
    client-side timer guessing how long the strike stays open.
    """

    _attr_supported_features = LockEntityFeature.OPEN

    def __init__(self, coordinator: HikvisionCoordinator, door_no: int) -> None:
        """Initialize a lock for the given 1-based door number."""
        super().__init__(coordinator)
        self._door_no = door_no
        serial = coordinator.data.device_info.serial_number
        self._attr_unique_id = f"{serial}_door_{door_no}"
        self._attr_translation_key = "door"
        self._attr_translation_placeholders = {"door": str(door_no)}
        self._attr_is_locked = True

    async def async_added_to_hass(self) -> None:
        """Subscribe to pushed events for door-state updates."""
        await super().async_added_to_hass()
        signal = SIGNAL_ACCESS_EVENT.format(self.coordinator.config_entry.entry_id)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_event),
        )

    @callback
    def _handle_event(self, event: DeviceEvent) -> None:
        """Sync locked state from the device's own door state events."""
        if event.door_no is not None and event.door_no != self._door_no:
            return
        if event.label in DOOR_OPEN_LABELS:
            self._attr_is_locked = False
            self.async_write_ha_state()
        elif event.label in DOOR_CLOSE_LABELS:
            self._attr_is_locked = True
            self.async_write_ha_state()

    async def async_open(self, **kwargs: Any) -> None:
        """Pulse the relay open.

        Doesn't set state directly — the resulting door_unlocked/door_locked
        events from the device (via _handle_event) are the source of truth.
        """
        await self.coordinator.client.open_door(self._door_no, cmd="open")

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock == momentary open for a door strike."""
        await self.async_open(**kwargs)

    async def async_lock(self, **kwargs: Any) -> None:
        """Explicitly close/lock the relay."""
        await self.coordinator.client.open_door(self._door_no, cmd="close")
