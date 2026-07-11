# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Parsing of the Hikvision ``alertStream`` (multipart/mixed of JSON parts).

The DS-KV9503-WBE1 has no HTTP-host webhook support, so events are consumed by
holding open ``GET /ISAPI/Event/notification/alertStream``. Each MIME part is a
JSON object; access events arrive as ``AccessControllerEvent`` carrying
``majorEventType``/``subEventType`` (the ACS event taxonomy) plus, when present,
``cardNo``/``employeeNoString``/``currentVerifyMode``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from .models import DeviceEvent

# Semantic labels for AccessControllerEvent subEventType (major event type 5).
# Focused on verification + door-state events; unknown codes fall back to
# ``acs_<major>_<sub>``. Source: ACS event table (SDK/ISAPI).
_ACS_SUBEVENT_LABELS: dict[int, str] = {
    0x01: "card_valid",
    0x06: "card_no_right",
    0x07: "card_invalid_period",
    0x08: "card_expired",
    0x09: "card_invalid",  # unregistered card — the brokerable one
    0x15: "door_unlocked",
    0x16: "door_locked",
    0x19: "door_open_normal",
    0x1A: "door_close_normal",
    0x1B: "door_open_abnormal",
    0x1C: "door_open_timeout",
    0x25: "doorbell_ringing",
    0x26: "fingerprint_valid",
    0x27: "fingerprint_invalid",
    0x33: "call_center",
    0x4B: "face_valid",
    0x4C: "face_invalid",
    0x50: "face_not_exist",
    # "Upload Device Unlocking Record Event" (ISAPI event-types reference).
    # Fired post-unlock with an `unlockType` qualifier (e.g. "password" for a
    # public/global password — not tied to any employeeNo). Audit-after-the-
    # fact, not a pre-open broker: the door has already opened by the time
    # this arrives. Live-confirmed on the KV9503 via a public-password entry.
    0xD6: "door_unlock_record",
    # More specific taxonomy entry for the same case; not observed live on
    # this firmware (it sends 0xd6 + unlockType="password" instead), but kept
    # for devices/firmware that do emit it directly.
    0xE5: "door_unlocked_by_public_password",
    # "Authentication via Password Failed" — live-confirmed to carry NO
    # credential value (no entered digits, no employeeNo): only major/sub
    # type, deviceNo, and a snapshot photo. A failed PIN/password attempt
    # cannot be brokered pre-open on this device (unlike an unregistered
    # card, which does expose cardNo — see card_invalid above).
    0x96: "password_auth_failed",
}

#: All stable semantic labels this module can produce for AccessControllerEvent
#: (major type 5), i.e. every value ``label`` may take besides the dynamic
#: ``acs_<major>_<sub>`` fallback for unrecognized codes. Single source of
#: truth — consumers (e.g. the HA event entity) should derive their known
#: event-type list from this instead of hand-maintaining a duplicate.
ACCESS_EVENT_LABELS: frozenset[str] = frozenset(
    {*_ACS_SUBEVENT_LABELS.values(), "door_unlocked_by_public_password"},
)


def _label(major: int | None, sub: int | None, unlock_type: str | None) -> str:
    """Return a stable semantic label for an ACS major/sub event code pair."""
    if major == 5 and sub == 0xD6 and unlock_type == "password":
        return "door_unlocked_by_public_password"
    if major == 5 and sub is not None and sub in _ACS_SUBEVENT_LABELS:
        return _ACS_SUBEVENT_LABELS[sub]
    if major is None and sub is None:
        return "unknown"
    return f"acs_{major}_{sub}"


def parse_event_json(obj: dict[str, Any]) -> DeviceEvent:
    """Convert one parsed alertStream JSON object into a :class:`DeviceEvent`.

    Args:
        obj: A single JSON part from the stream.

    Returns:
        The typed event. Non-access events keep their top-level ``eventType`` and
        a best-effort label.

    """
    event_type = str(obj.get("eventType", "unknown"))
    ace = obj.get("AccessControllerEvent") or {}
    major = ace.get("majorEventType")
    sub = ace.get("subEventType")

    def _int(value: Any) -> int | None:
        """Coerce a JSON value to ``int`` when it already is one, else ``None``."""
        return int(value) if isinstance(value, int) else None

    unlock_type = ace.get("unlockType")
    label = (
        _label(_int(major), _int(sub), unlock_type)
        if event_type == "AccessControllerEvent"
        else event_type
    )
    return DeviceEvent(
        event_type=event_type,
        label=label,
        timestamp=obj.get("dateTime"),
        major_event_type=_int(major),
        sub_event_type=_int(sub),
        card_no=ace.get("cardNo"),
        # ISAPI uses employeeNoString on newer firmware, employeeNo on older.
        # Empty string for global/public-password unlocks (not tied to a person).
        employee_no=ace.get("employeeNoString") or ace.get("employeeNo") or None,
        name=ace.get("name"),
        verify_mode=ace.get("currentVerifyMode"),
        unlock_type=unlock_type,
        serial_no=_int(ace.get("serialNo")),
        door_no=_int(ace.get("doorNo")),
        raw=obj,
    )


def _content_length(headers: bytes) -> int | None:
    """Extract the ``Content-Length`` value from a MIME part's headers."""
    for line in headers.splitlines():
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None


def iter_multipart_json(body: bytes, boundary: str) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a complete multipart/mixed ``alertStream`` body.

    Splits on the MIME ``boundary`` and extracts the JSON payload after each
    part's blank-line header separator, trimmed to the part's own
    ``Content-Length`` when present (rather than assuming the payload ends
    right before the next boundary — a following binary part, e.g. a JPEG
    snapshot, can otherwise bleed into the JSON body and corrupt it).
    Malformed / non-JSON / non-UTF-8 parts are skipped, never raised.

    Args:
        body: The (buffered) multipart bytes.
        boundary: The boundary token (without leading dashes).

    Yields:
        Parsed JSON objects, one per MIME part.

    """
    delimiter = f"--{boundary}".encode()
    for part in body.split(delimiter):
        part = part.strip()
        if not part or part == b"--":
            continue
        # Headers and body are separated by a blank line (CRLF CRLF or LF LF).
        sep = b"\r\n\r\n" if b"\r\n\r\n" in part else b"\n\n"
        headers, _, payload = part.partition(sep)
        payload = payload.strip()
        if not payload.startswith(b"{"):
            continue
        length = _content_length(headers)
        if length is not None:
            payload = payload[:length]
        try:
            yield json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            continue


async def iter_stream_events(
    lines: AsyncIterator[bytes],
    boundary: str,
) -> AsyncIterator[DeviceEvent]:
    """Parse a live multipart byte stream into :class:`DeviceEvent` objects.

    Buffers bytes and emits an event each time a full MIME part (terminated by
    the next boundary) is available. Designed for ``httpx`` streaming responses.

    Args:
        lines: Async iterator of raw byte chunks from the response body.
        boundary: The MIME boundary token (without leading dashes).

    Yields:
        Parsed :class:`DeviceEvent` objects as they arrive.

    """
    delimiter = f"--{boundary}".encode()
    buffer = b""
    async for chunk in lines:
        buffer += chunk
        while True:
            first = buffer.find(delimiter)
            if first < 0:
                break
            nxt = buffer.find(delimiter, first + len(delimiter))
            if nxt < 0:
                break
            segment = buffer[first:nxt]
            buffer = buffer[nxt:]
            for obj in iter_multipart_json(segment, boundary):
                yield parse_event_json(obj)
