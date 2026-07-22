# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Binary sensors — device connectivity and door contact state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Create the connectivity sensor plus a single shared door-contact sensor."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            HikvisionOnlineSensor(coordinator),
            HikvisionDoorContact(coordinator),
        ],
    )


class HikvisionOnlineSensor(HikvisionEntity, BinarySensorEntity):
    """Connectivity sensor driven by coordinator success."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "online"
    _attr_entity_category = None

    def __init__(self, coordinator: HikvisionCoordinator) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(coordinator)
        serial = coordinator.data.device_info.serial_number
        self._attr_unique_id = f"{serial}_online"

    @property
    def is_on(self) -> bool:
        """Return True when the last coordinator update succeeded."""
        return self.coordinator.last_update_success


class HikvisionDoorContact(HikvisionEntity, BinarySensorEntity):
    """Door open/closed state, updated from pushed access events.

    A single shared sensor across all doors: this device's door-contact
    events (live-confirmed on hardware) carry no field identifying which of
    its multiple physical inputs changed, so per-door attribution isn't
    possible from this event stream. Unlike door contacts, relay/lock
    commands ARE addressed to a specific door number and stay one entity per
    door (see lock.py) — only the input side is ambiguous.
    """

    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_translation_key = "door_contact"

    def __init__(self, coordinator: HikvisionCoordinator) -> None:
        """Initialize the shared door-contact sensor."""
        super().__init__(coordinator)
        serial = coordinator.data.device_info.serial_number
        self._attr_unique_id = f"{serial}_door_contact"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to pushed events for door-state updates."""
        await super().async_added_to_hass()
        signal = SIGNAL_ACCESS_EVENT.format(self.coordinator.config_entry.entry_id)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_event),
        )

    @callback
    def _handle_event(self, event: DeviceEvent) -> None:
        """Flip state when a door open/close event arrives (any input)."""
        if event.label in DOOR_OPEN_LABELS:
            self._attr_is_on = True
            self.async_write_ha_state()
        elif event.label in DOOR_CLOSE_LABELS:
            self._attr_is_on = False
            self.async_write_ha_state()
