# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Lock entities — one per door relay (momentary open)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DOOR_RELOCK_DELAY
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
        self._cancel_relock: Callable[[], None] | None = None

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any pending auto-relock timer on removal."""
        self._cancel_pending_relock()

    def _cancel_pending_relock(self) -> None:
        """Cancel a scheduled auto-relock, if one is pending."""
        if self._cancel_relock is not None:
            self._cancel_relock()
            self._cancel_relock = None

    def _schedule_relock(self) -> None:
        """Revert to "locked" after a delay, cancelling any prior timer.

        Approximates the strike's own hold-open time, since the device
        reports no re-lock event to sync against. Cancelling any previously
        scheduled revert first means repeated opens don't race each other.
        """
        self._cancel_pending_relock()
        self._cancel_relock = async_call_later(
            self.hass,
            DOOR_RELOCK_DELAY,
            self._handle_relock,
        )

    @callback
    def _handle_relock(self, _now: object) -> None:
        """Flip back to "locked" once the relock delay elapses."""
        self._cancel_relock = None
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def async_open(self, **kwargs: Any) -> None:
        """Pulse the relay open, reflecting the new state in HA."""
        await self.coordinator.client.open_door(self._door_no, cmd="open")
        self._attr_is_locked = False
        self.async_write_ha_state()
        self._schedule_relock()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock == momentary open for a door strike."""
        await self.async_open(**kwargs)

    async def async_lock(self, **kwargs: Any) -> None:
        """Explicitly close/lock the relay, reflecting the new state in HA."""
        self._cancel_pending_relock()
        await self.coordinator.client.open_door(self._door_no, cmd="close")
        self._attr_is_locked = True
        self.async_write_ha_state()
