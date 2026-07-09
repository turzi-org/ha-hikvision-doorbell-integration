# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Domain services for credential and door management."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from pylocal_hikvision import (
    Card,
    HikvisionClient,
    HikvisionError,
    Person,
    Validity,
)

from .const import DOMAIN
from .coordinator import HikvisionConfigEntry, HikvisionCoordinator

ATTR_DEVICE_ID = "device_id"
ATTR_EMPLOYEE_NO = "employee_no"

_BASE = {vol.Required(ATTR_DEVICE_ID): cv.string}

SERVICE_SCHEMAS = {
    "open_door": vol.Schema({**_BASE, vol.Required("door_no"): vol.Coerce(int)}),
    "add_user": vol.Schema(
        {
            **_BASE,
            vol.Required(ATTR_EMPLOYEE_NO): cv.string,
            vol.Required("name"): cv.string,
            vol.Optional("room_number"): vol.Coerce(int),
            vol.Optional("floor_number"): vol.Coerce(int),
            vol.Optional("valid_begin"): cv.datetime,
            vol.Optional("valid_end"): cv.datetime,
        },
    ),
    "add_card": vol.Schema(
        {
            **_BASE,
            vol.Required(ATTR_EMPLOYEE_NO): cv.string,
            vol.Required("card_no"): cv.string,
        },
    ),
    "upload_face": vol.Schema(
        {
            **_BASE,
            vol.Required(ATTR_EMPLOYEE_NO): cv.string,
            vol.Required("image_path"): cv.string,
        },
    ),
    "delete_user": vol.Schema({**_BASE, vol.Required(ATTR_EMPLOYEE_NO): cv.string}),
    "delete_card": vol.Schema({**_BASE, vol.Required(ATTR_EMPLOYEE_NO): cv.string}),
    "set_remote_check": vol.Schema(
        {
            **_BASE,
            vol.Required("enabled"): cv.boolean,
            vol.Optional("timeout"): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
        },
    ),
}


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> HikvisionCoordinator:
    """Resolve the target ``device_id`` to its coordinator."""
    device_id = call.data[ATTR_DEVICE_ID]
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(f"Unknown device_id: {device_id}")
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN:
            return cast(HikvisionConfigEntry, entry).runtime_data
    raise ServiceValidationError(f"Device {device_id} is not a {DOMAIN} device")


def _validity(call: ServiceCall) -> Validity | None:
    """Build a Validity from optional valid_begin/valid_end fields."""
    begin = call.data.get("valid_begin")
    end = call.data.get("valid_end")
    if begin is None or end is None:
        return None
    return Validity(begin=begin, end=end)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register domain services (idempotent across entries)."""
    if hass.services.has_service(DOMAIN, "open_door"):
        return

    async def _run(call: ServiceCall) -> None:
        client = _coordinator(hass, call).client
        try:
            await _dispatch(hass, client, call)
        except HikvisionError as err:
            raise HomeAssistantError(str(err)) from err

    for name, schema in SERVICE_SCHEMAS.items():
        hass.services.async_register(DOMAIN, name, _run, schema=schema)


async def _dispatch(
    hass: HomeAssistant,
    client: HikvisionClient,
    call: ServiceCall,
) -> None:
    """Route a validated service call to the matching client method."""
    service = call.service
    if service == "open_door":
        await client.open_door(call.data["door_no"])
    elif service == "add_user":
        await client.add_user(
            Person(
                employee_no=call.data[ATTR_EMPLOYEE_NO],
                name=call.data["name"],
                room_number=call.data.get("room_number"),
                floor_number=call.data.get("floor_number"),
                validity=_validity(call),
            ),
        )
    elif service == "add_card":
        await client.add_card(
            Card(employee_no=call.data[ATTR_EMPLOYEE_NO], card_no=call.data["card_no"]),
        )
    elif service == "upload_face":
        image = await hass.async_add_executor_job(
            Path(call.data["image_path"]).read_bytes,
        )
        await client.add_face(call.data[ATTR_EMPLOYEE_NO], image)
    elif service == "delete_user":
        await client.delete_user(call.data[ATTR_EMPLOYEE_NO])
    elif service == "delete_card":
        await client.delete_card(call.data[ATTR_EMPLOYEE_NO])
    elif service == "set_remote_check":
        await client.set_remote_check(
            enabled=call.data["enabled"],
            timeout=call.data.get("timeout"),
        )
