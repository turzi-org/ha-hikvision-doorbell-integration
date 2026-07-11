# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Event entity surfacing access events (card/face/door) from the stream."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_ACCESS, SIGNAL_ACCESS_EVENT
from .coordinator import HikvisionConfigEntry, HikvisionCoordinator
from .entity import HikvisionEntity
from .isapi import ACCESS_EVENT_LABELS, DeviceEvent

# The set of access-event labels this entity advertises + relays, derived from
# isapi.events' single source of truth so it can't drift out of sync as new
# labels are added there. "other" is the catch-all for anything not in that
# set (non-ACS events, or an unrecognized ACS code).
_EVENT_TYPES = [*sorted(ACCESS_EVENT_LABELS), "other"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikvisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the single access-event entity for the device."""
    async_add_entities([HikvisionAccessEvent(entry.runtime_data)])


class HikvisionAccessEvent(HikvisionEntity, EventEntity):
    """Fires whenever an access event is parsed from the alertStream."""

    _attr_translation_key = "access"
    _attr_event_types = _EVENT_TYPES

    def __init__(self, coordinator: HikvisionCoordinator) -> None:
        """Initialize the access-event entity."""
        super().__init__(coordinator)
        serial = coordinator.data.device_info.serial_number
        self._attr_unique_id = f"{serial}_access_event"

    async def async_added_to_hass(self) -> None:
        """Subscribe to the pushed event stream."""
        await super().async_added_to_hass()
        signal = SIGNAL_ACCESS_EVENT.format(self.coordinator.config_entry.entry_id)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_event),
        )

    @callback
    def _handle_event(self, event: DeviceEvent) -> None:
        """Relay a parsed event as an HA event + fire it on the event bus."""
        # Ignore non-access noise (videoloss, heartbeats).
        if event.event_type != "AccessControllerEvent":
            return
        event_type = event.label if event.label in _EVENT_TYPES else "other"
        attributes = {
            "label": event.label,
            "card_no": event.card_no,
            "employee_no": event.employee_no,
            "name": event.name,
            "verify_mode": event.verify_mode,
            "door_no": event.door_no,
            "serial_no": event.serial_no,
        }
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()
        self.hass.bus.async_fire(
            EVENT_ACCESS,
            {"entity_id": self.entity_id, **attributes},
        )
