# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Lock entities — one per door relay (momentary open)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HikvisionConfigEntry, HikvisionCoordinator
from .entity import HikvisionEntity


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
    """A door relay exposed as a lock supporting the momentary open action."""

    _attr_supported_features = LockEntityFeature.OPEN

    def __init__(self, coordinator: HikvisionCoordinator, door_no: int) -> None:
        """Initialize a lock for the given 1-based door number."""
        super().__init__(coordinator)
        self._door_no = door_no
        serial = coordinator.data.device_info.serial_number
        self._attr_unique_id = f"{serial}_door_{door_no}"
        self._attr_translation_key = "door"
        self._attr_translation_placeholders = {"door": str(door_no)}
        # Door strikes are momentary; there is no persistent locked/unlocked state
        # to read back, so present as locked and rely on the open action.
        self._attr_is_locked = True

    async def async_open(self, **kwargs: Any) -> None:
        """Pulse the relay open."""
        await self.coordinator.client.open_door(self._door_no, cmd="open")

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock == momentary open for a door strike."""
        await self.coordinator.client.open_door(self._door_no, cmd="open")

    async def async_lock(self, **kwargs: Any) -> None:
        """Explicitly close/lock the relay."""
        await self.coordinator.client.open_door(self._door_no, cmd="close")
