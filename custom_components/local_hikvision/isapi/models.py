# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Typed data models returned by the client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Identity of a Hikvision device, from ``/ISAPI/System/deviceInfo``."""

    model: str
    serial_number: str
    firmware_version: str
    device_name: str = ""
    device_type: str = ""
    mac_address: str = ""


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a device supports, resolved from ISAPI capability probes.

    Populated incrementally as the client learns endpoints. Fields default to
    ``None`` meaning "not yet probed / unknown" rather than "unsupported".
    """

    door_count: int | None = None
    supports_pin: bool | None = None
    supports_card: bool | None = None
    supports_face: bool | None = None
    #: Whether an unknown/failed credential attempt is reported (with its value)
    #: so remote verification can broker it. The key open hardware question.
    reports_attempted_credential: bool | None = None
    #: Whether the device supports native remote verification (AcsCfg /
    #: isSupportRemoteCheck) — the door defers the grant decision to a platform.
    supports_remote_check: bool | None = None
    max_users: int | None = None
    max_cards: int | None = None
    max_faces: int | None = None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeviceEvent:
    """A single event parsed from the ``alertStream`` (``AccessControllerEvent``).

    ``label`` is a stable semantic name derived from ``major_event_type`` /
    ``sub_event_type`` (e.g. ``card_invalid``, ``door_unlocked``) so callers
    don't hard-code Hikvision numeric codes. Credential fields are populated only
    when the underlying event carries them.
    """

    event_type: str
    label: str
    timestamp: str | None = None
    major_event_type: int | None = None
    sub_event_type: int | None = None
    card_no: str | None = None
    employee_no: str | None = None
    name: str | None = None
    verify_mode: str | None = None
    serial_no: int | None = None
    door_no: int | None = None
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UserCount:
    """Enrollment counts from ``/ISAPI/AccessControl/UserInfo/Count``."""

    users: int
    faces: int
    cards: int


@dataclass(frozen=True, slots=True)
class Validity:
    """A credential/person validity window (maps to ISAPI ``UserInfo.Valid``)."""

    begin: datetime
    end: datetime
    enable: bool = True
    #: ``local`` or ``UTC`` (per the device's ``Valid.@opt``).
    time_type: str = "local"

    def to_isapi(self) -> dict[str, object]:
        """Serialize to the ISAPI ``Valid`` JSON object."""
        return {
            "enable": self.enable,
            "beginTime": self.begin.strftime("%Y-%m-%dT%H:%M:%S"),
            "endTime": self.end.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeType": self.time_type,
        }


@dataclass(frozen=True, slots=True)
class Person:
    """A person/user to enroll on the device (maps to ISAPI ``UserInfo``).

    Field set matches the DS-KV9503-WBE1's actual ``UserInfo`` records (a VIS
    door station). Notes from live inspection:

    - **Per-user PIN = ``dynamicCode``.** Confirmed by round-trip on real
      hardware: written via ``add_user``, read back unchanged via
      ``search_users``. Absent from most existing records simply because those
      residents authenticate with card/face instead — the field itself works.
      On the physical keypad it is entered as ``# + Room No. + PIN + OK``,
      i.e. the device resolves ``room_number`` to a person, then checks
      ``dynamicCode``. Set ``room_number`` alongside ``pin`` for keypad entry
      to work.
    - **No door-rights field.** Rights/schedules are assigned via separate
      endpoints keyed by ``employee_no`` (``UserRightWeekPlanCfg`` etc.) — but
      this device doesn't support those (see the integration's device-limits
      notes); only the ``Valid`` window applies.
    """

    employee_no: str
    name: str
    user_type: str = "normal"
    validity: Validity | None = None
    floor_number: int | None = None
    room_number: int | None = None
    pin: str | None = None


@dataclass(frozen=True, slots=True)
class Card:
    """A card/tag credential (maps to ISAPI ``CardInfo``)."""

    employee_no: str
    card_no: str
    card_type: str = "normalCard"


@dataclass(frozen=True, slots=True)
class AcsConfig:
    """Access-control config (ISAPI ``AcsCfg``) — the native remote-verify switch.

    On this device the exposed set is coarse: an on/off ``remote_check_enabled``
    plus a ``remote_check_timeout`` (seconds). When enabled, the device defers
    the door-open decision to the platform; if no verdict arrives within the
    timeout the attempt fails.
    """

    remote_check_enabled: bool
    remote_check_timeout: int
