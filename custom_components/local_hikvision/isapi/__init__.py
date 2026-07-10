# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Async local ISAPI client for Hikvision door stations."""

from __future__ import annotations

from .client import HikvisionClient
from .errors import (
    HikvisionAuthenticationError,
    HikvisionConnectionError,
    HikvisionError,
    HikvisionParseError,
    HikvisionResponseError,
)
from .models import (
    AcsConfig,
    Capabilities,
    Card,
    DeviceEvent,
    DeviceInfo,
    Person,
    UserCount,
    Validity,
)

__all__ = [
    "AcsConfig",
    "Capabilities",
    "Card",
    "DeviceEvent",
    "DeviceInfo",
    "HikvisionAuthenticationError",
    "HikvisionClient",
    "HikvisionConnectionError",
    "HikvisionError",
    "HikvisionParseError",
    "HikvisionResponseError",
    "Person",
    "UserCount",
    "Validity",
]
