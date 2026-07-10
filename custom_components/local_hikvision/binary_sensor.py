# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Binary sensors — device connectivity and per-door contact state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pylocal_hikvision import DeviceEvent

from .const import DOOR_CLOSE_LABELS, DOOR_OPEN_LABELS, SIGNAL_ACCESS_EVENT
from .coordinator import HikvisionConfigEntry, HikvisionCoordinator
from .entity import HikvisionEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikvisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the connectivity sensor plus one door-contact sensor per door."""
    coordinator = entry.runtime_data
    door_count = coordinator.data.capabilities.door_count or 1
    entities: list[BinarySensorEntity] = [HikvisionOnlineSensor(coordinator)]
    entities.extend(
        HikvisionDoorContact(coordinator, door_no)
        for door_no in range(1, door_count + 1)
    )
    async_add_entities(entities)


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
    """Door open/closed state, updated from pushed access events."""

    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, coordinator: HikvisionCoordinator, door_no: int) -> None:
        """Initialize a door-contact sensor for the given door number."""
        super().__init__(coordinator)
        self._door_no = door_no
        serial = coordinator.data.device_info.serial_number
        self._attr_unique_id = f"{serial}_door_{door_no}_contact"
        self._attr_translation_key = "door_contact"
        self._attr_translation_placeholders = {"door": str(door_no)}
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
        """Flip state when a matching door open/close event arrives."""
        if event.door_no is not None and event.door_no != self._door_no:
            return
        if event.label in DOOR_OPEN_LABELS:
            self._attr_is_on = True
            self.async_write_ha_state()
        elif event.label in DOOR_CLOSE_LABELS:
            self._attr_is_on = False
            self.async_write_ha_state()
