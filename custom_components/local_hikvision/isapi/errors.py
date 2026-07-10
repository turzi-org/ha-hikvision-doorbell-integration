# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Exception types raised by :mod:`pylocal_hikvision`.

The hierarchy mirrors the shape of ``pylocal_akuvox`` so the sibling Home
Assistant integrations can handle both brands with the same ``except`` clauses.
"""

from __future__ import annotations


class HikvisionError(Exception):
    """Base class for all errors raised by this library."""


class HikvisionConnectionError(HikvisionError):
    """The device could not be reached (network/timeout/TLS failure)."""


class HikvisionAuthenticationError(HikvisionError):
    """Authentication with the device failed (bad credentials/privilege)."""


class HikvisionResponseError(HikvisionError):
    """The device returned an unexpected HTTP status or ISAPI error body."""


class HikvisionParseError(HikvisionError):
    """A device response could not be parsed into the expected shape."""
