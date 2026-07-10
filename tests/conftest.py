# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Test bootstrap: expose the folded-in ISAPI package as top-level ``isapi``.

This lets the HA-free protocol tests run with plain pytest (no Home Assistant),
by importing ``custom_components/local_hikvision/isapi`` without pulling the
integration package (which imports homeassistant).
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "custom_components" / "local_hikvision"))
