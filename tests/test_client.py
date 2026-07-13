# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Tests for HikvisionClient-level behavior not covered elsewhere."""

from __future__ import annotations

from collections.abc import AsyncIterator

from isapi import DeviceEvent, HikvisionClient
from isapi.errors import HikvisionAuthenticationError


async def test_stream_events_reconnecting_recovers_from_auth_error() -> None:
    # Regression: a 401 mid-stream (the device expiring its digest nonce
    # under sustained use) must not kill the reconnecting generator — it
    # should reset auth and keep going, the same recovery _request already
    # does for one-shot calls.
    client = HikvisionClient("10.0.0.5", "admin", "secret")
    original_auth = client._client.auth
    calls = 0

    async def fake_stream_events() -> AsyncIterator[DeviceEvent]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HikvisionAuthenticationError("Unauthorized on alertStream")
            yield  # pragma: no cover - unreachable, makes this an async gen
        yield DeviceEvent(event_type="videoloss", label="videoloss")

    client.stream_events = fake_stream_events  # type: ignore[method-assign]

    events = []
    async for event in client.stream_events_reconnecting(base_backoff=0):
        events.append(event)
        break

    assert calls == 2
    assert events == [DeviceEvent(event_type="videoloss", label="videoloss")]
    assert client._client.auth is not original_auth  # a fresh challenge was set
