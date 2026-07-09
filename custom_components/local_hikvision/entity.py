# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Base entity wiring shared device info + coordinator access."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo as HADeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HikvisionCoordinator


class HikvisionEntity(CoordinatorEntity[HikvisionCoordinator]):
    """Base class attaching entities to the device registry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HikvisionCoordinator) -> None:
        """Initialize with the shared coordinator."""
        super().__init__(coordinator)
        info = coordinator.data.device_info
        self._attr_device_info = HADeviceInfo(
            identifiers={(DOMAIN, info.serial_number)},
            manufacturer="Hikvision",
            model=info.model,
            name=info.device_name or info.model,
            sw_version=info.firmware_version,
            serial_number=info.serial_number,
        )
