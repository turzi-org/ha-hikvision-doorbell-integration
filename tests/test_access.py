# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Tests for access-control operations, mocked with respx.

Request bodies are asserted against the ISAPI spec + the real DS-KV9503-WBE1
capability shapes. Live device writes are validated separately on non-prod.
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
import respx
from isapi import (
    Card,
    HikvisionClient,
    HikvisionResponseError,
    Person,
    UserCount,
    Validity,
)

BASE = "http://10.0.0.5:80"
_OK = {"statusCode": 1, "statusString": "OK", "subStatusCode": "ok"}


def _client() -> HikvisionClient:
    return HikvisionClient("10.0.0.5", "admin", "secret")


@respx.mock
async def test_get_user_count() -> None:
    respx.get(f"{BASE}/ISAPI/AccessControl/UserInfo/Count").mock(
        return_value=httpx.Response(
            200,
            json={
                "UserInfoCount": {
                    "userNumber": 88,
                    "bindFaceUserNumber": 42,
                    "bindCardUserNumber": 46,
                },
            },
        ),
    )
    async with _client() as c:
        assert await c.get_user_count() == UserCount(users=88, faces=42, cards=46)


@respx.mock
async def test_add_user_builds_expected_body() -> None:
    route = respx.post(f"{BASE}/ISAPI/AccessControl/UserInfo/Record").mock(
        return_value=httpx.Response(200, json=_OK),
    )
    person = Person(
        employee_no="1001",
        name="Test Person",
        validity=Validity(
            begin=datetime(2026, 1, 1, 0, 0, 0),
            end=datetime(2026, 12, 31, 23, 59, 59),
        ),
        room_number=305,
    )
    async with _client() as c:
        await c.add_user(person)

    request = route.calls.last.request
    assert request.headers["content-type"] == "application/json"
    sent = json.loads(request.content)["UserInfo"]
    assert sent["employeeNo"] == "1001"
    assert sent["name"] == "Test Person"
    assert sent["userType"] == "normal"
    assert sent["Valid"]["beginTime"] == "2026-01-01T00:00:00"
    assert sent["Valid"]["endTime"] == "2026-12-31T23:59:59"
    assert sent["roomNumber"] == 305


@respx.mock
async def test_add_card_body() -> None:
    route = respx.post(f"{BASE}/ISAPI/AccessControl/CardInfo/Record").mock(
        return_value=httpx.Response(200, json=_OK),
    )
    async with _client() as c:
        await c.add_card(Card(employee_no="1001", card_no="0012345678"))
    sent = json.loads(route.calls.last.request.content)["CardInfo"]
    assert sent == {
        "employeeNo": "1001",
        "cardNo": "0012345678",
        "cardType": "normalCard",
    }


@respx.mock
async def test_open_door_sends_xml() -> None:
    route = respx.put(f"{BASE}/ISAPI/AccessControl/RemoteControl/door/1").mock(
        return_value=httpx.Response(200, text="<ResponseStatus/>"),
    )
    async with _client() as c:
        await c.open_door(1)
    assert route.calls.last.request.content == (
        b"<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>"
    )


@respx.mock
async def test_isapi_error_envelope_raises() -> None:
    respx.put(f"{BASE}/ISAPI/AccessControl/UserInfo/Delete").mock(
        return_value=httpx.Response(
            200,
            json={
                "statusCode": 6,
                "statusString": "Invalid Content",
                "subStatusCode": "badJsonContent",
                "errorMsg": "badJsonContent",
            },
        ),
    )
    async with _client() as c:
        with pytest.raises(HikvisionResponseError, match="badJsonContent"):
            await c.delete_user("1001")
