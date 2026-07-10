# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Tests for AcsCfg (remote verification) read/write and the reconnecting stream."""

from __future__ import annotations

import json

import httpx
import respx
from isapi import AcsConfig, HikvisionClient

BASE = "http://10.0.0.5:80"
_OK = {"statusCode": 1, "statusString": "OK", "subStatusCode": "ok"}


def _client() -> HikvisionClient:
    return HikvisionClient("10.0.0.5", "admin", "secret")


@respx.mock
async def test_get_acs_config() -> None:
    respx.get(f"{BASE}/ISAPI/AccessControl/AcsCfg").mock(
        return_value=httpx.Response(
            200,
            json={"AcsCfg": {"remoteCheckDoorEnabled": False, "remoteCheckTimeout": 5}},
        ),
    )
    async with _client() as c:
        assert await c.get_acs_config() == AcsConfig(
            remote_check_enabled=False,
            remote_check_timeout=5,
        )


@respx.mock
async def test_set_remote_check_body_and_content_type() -> None:
    route = respx.put(f"{BASE}/ISAPI/AccessControl/AcsCfg").mock(
        return_value=httpx.Response(200, json=_OK),
    )
    async with _client() as c:
        await c.set_remote_check(enabled=True, timeout=7)
    request = route.calls.last.request
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "AcsCfg": {"remoteCheckDoorEnabled": True, "remoteCheckTimeout": 7},
    }
