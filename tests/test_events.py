# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Tests for alertStream parsing, using a real captured multipart sample."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from isapi.events import (
    iter_multipart_json,
    iter_stream_events,
    parse_event_json,
)

# Shaped after a real capture from the DS-KV9503-WBE1 (backlog event) plus a
# synthetic unregistered-card event (the brokerable case).
_SAMPLE = (
    b"--MIME_boundary\r\n"
    b'Content-Type: application/json\r\n\r\n'
    b'{"eventType":"AccessControllerEvent","dateTime":"2026-07-07T22:55:56-03:00",'
    b'"AccessControllerEvent":{"majorEventType":5,"subEventType":9,'
    b'"cardNo":"0012345678","currentVerifyMode":"cardOrFaceOrFp","serialNo":42}}\r\n'
    b"--MIME_boundary\r\n"
    b"Content-Type: application/json\r\n\r\n"
    b'{"eventType":"AccessControllerEvent","dateTime":"2026-07-07T22:55:58-03:00",'
    b'"AccessControllerEvent":{"majorEventType":5,"subEventType":1,'
    b'"cardNo":"0099999999","employeeNoString":"1001","name":"Resident","serialNo":43}}\r\n'
    b"--MIME_boundary--\r\n"
)


def test_public_password_unlock_labeled_and_not_tied_to_person() -> None:
    # Real event captured on the non-prod KV9503 while entering "#9876" at the
    # keypad (a public/global password, not linked to any UserInfo record).
    obj = {
        "eventType": "AccessControllerEvent",
        "dateTime": "2026-06-02T13:23:29+08:00",
        "AccessControllerEvent": {
            "majorEventType": 5,
            "subEventType": 214,
            "employeeNoString": "",
            "mask": "unknown",
            "unlockType": "password",
            "deviceNo": "10010100000",
            "currentEvent": False,
            "picturesNumber": 1,
        },
    }
    ev = parse_event_json(obj)
    assert ev.label == "door_unlocked_by_public_password"
    assert ev.unlock_type == "password"
    assert ev.employee_no is None  # confirms it's genuinely not tied to a person


def test_iter_multipart_json_extracts_parts() -> None:
    objs = list(iter_multipart_json(_SAMPLE, "MIME_boundary"))
    assert len(objs) == 2
    assert objs[0]["AccessControllerEvent"]["subEventType"] == 9


def test_parse_invalid_card_event() -> None:
    obj = next(iter(iter_multipart_json(_SAMPLE, "MIME_boundary")))
    ev = parse_event_json(obj)
    assert ev.label == "card_invalid"  # 0x09 — the brokerable unregistered card
    assert ev.card_no == "0012345678"
    assert ev.major_event_type == 5
    assert ev.sub_event_type == 9
    assert ev.serial_no == 42


def test_parse_valid_card_event_employee() -> None:
    obj = list(iter_multipart_json(_SAMPLE, "MIME_boundary"))[1]
    ev = parse_event_json(obj)
    assert ev.label == "card_valid"
    assert ev.employee_no == "1001"
    assert ev.name == "Resident"


async def test_iter_stream_events_over_chunks() -> None:
    # Feed the sample in small chunks to exercise incremental buffering.
    async def chunks() -> AsyncIterator[bytes]:
        for i in range(0, len(_SAMPLE), 17):
            yield _SAMPLE[i : i + 17]

    labels = [ev.label async for ev in iter_stream_events(chunks(), "MIME_boundary")]
    assert labels == ["card_invalid", "card_valid"]


def test_unknown_subevent_falls_back() -> None:
    ev = parse_event_json(
        {"eventType": "AccessControllerEvent", "AccessControllerEvent": {
            "majorEventType": 5, "subEventType": 999}},
    )
    assert ev.label == "acs_5_999"


@pytest.mark.parametrize(
    ("sub", "label"),
    [(9, "card_invalid"), (1, "card_valid"), (0x1C, "door_open_timeout"),
     (0x4C, "face_invalid")],
)
def test_label_mapping(sub: int, label: str) -> None:
    ev = parse_event_json(
        {"eventType": "AccessControllerEvent",
         "AccessControllerEvent": {"majorEventType": 5, "subEventType": sub}},
    )
    assert ev.label == label
