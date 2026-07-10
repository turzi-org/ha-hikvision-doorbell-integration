<!--
SPDX-FileCopyrightText: 2026 Turzi
SPDX-License-Identifier: Apache-2.0
-->

# Turzi Local Hikvision

A local-push [Home Assistant](https://www.home-assistant.io/) integration for
Hikvision **video-intercom door stations**, speaking pure **ISAPI over HTTP** — no
cloud, no binary SDK. Companion to the Turzi access-control platform and the
[Akuvox integration](https://github.com/turzi-org/homeassistant-local-akuvox).

<p align="center">
  <img alt="HACS Custom" src="https://img.shields.io/badge/HACS-Custom-orange?style=flat-square">
  <img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-2026.2%2B-blue?style=flat-square&logo=home-assistant">
  <img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-green?style=flat-square">
</p>

> **Status:** early / beta. Read-only features are validated against real hardware.
> The credential/door **write** services are implemented but not yet validated on a
> device — use a non-production unit. See [Device limitations](#device-limitations).

## Features

- **Door control** — each door relay is a `lock` entity with a momentary open action.
- **Live events** — a long-lived `alertStream` connection surfaces access events
  (card/face/door) as an `event` entity and on the Home Assistant event bus, with
  automatic reconnect.
- **Door & connectivity state** — `binary_sensor` entities for per-door contact and
  device online status.
- **Credential management services** — enroll/remove people, cards, and faces;
  actuate doors; toggle native remote verification.
- **Zero external dependencies** — the ISAPI client is vendored and uses only
  `httpx` + the standard library, both shipped by Home Assistant.

## Supported devices

Developed and tested against the **DS-KV9503-WBE1** (VIS door station, firmware
V2.3.13). Other Hikvision ISAPI door stations may work; capabilities are probed at
setup, so unsupported endpoints degrade gracefully.

## Installation

The integration is self-contained — nothing to `pip install`.

**Manual**
1. Copy `custom_components/local_hikvision/` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

**HACS** (custom repository)
1. HACS → Integrations → ⋮ → *Custom repositories* → add
   `https://github.com/turzi-org/ha-hikvision-doorbell-integration` (category
   *Integration*).
2. Install, then restart Home Assistant.

Then: **Settings → Devices & Services → Add Integration → “Turzi Local Hikvision”**.

## Configuration

| Field | Notes |
|-------|-------|
| Host | Device IP or hostname |
| Username / Password | An ISAPI account with AccessControl privileges |
| Port | Default `80` |
| Use HTTPS | Off by default |

The device serial number is used as the unique id, so the same device can't be
added twice.

## Entities

| Entity | Platform | Description |
|--------|----------|-------------|
| Door *N* | `lock` | One per door relay; supports the open action |
| Door *N* contact | `binary_sensor` (door) | Open/closed, from pushed events |
| Online | `binary_sensor` (connectivity) | Device reachability |
| Access | `event` | Fires on card/face/door access events |

## Services

All services target a device via `device_id`.

| Service | Purpose |
|---------|---------|
| `local_hikvision.open_door` | Momentarily open a door relay |
| `local_hikvision.add_user` | Enroll a person (identity + validity window) |
| `local_hikvision.add_card` | Enroll a card/tag for a person |
| `local_hikvision.upload_face` | Enroll a face picture from a local JPEG |
| `local_hikvision.delete_user` | Remove a person and their credentials |
| `local_hikvision.delete_card` | Remove a person's card(s) |
| `local_hikvision.set_remote_check` | Enable/disable native remote verification |

> ⚠️ `set_remote_check` is behavior-changing on a live door: when enabled, the
> device defers entry decisions to your platform and **locks people out** if no
> verdict arrives within the timeout. Only use it with a responding verifier.

## Device limitations

The DS-KV9503-WBE1 is a video-intercom door station, not a full access controller.
Confirmed against real hardware:

| Per-user feature | Supported |
|------------------|-----------|
| Card / tag | ✅ |
| Face | ✅ (write-only — no face search) |
| QR code | ✅ |
| Validity window (start/end) | ✅ |
| **Per-user PIN** | ❌ not stored on the device |
| **Weekly / holiday schedules** | ❌ not supported |
| Native remote verification | ✅ (coarse on/off) |

**Implication:** per-resident **PINs** and **time schedules** are *not* something this
device stores locally — they can only be handled by your platform via **remote
verification** (the device asks your server at entry time). Cards and faces are the
per-person credentials that live on the device. This differs from the Akuvox
integration, where per-user PINs and schedules are local.

## Development

The vendored ISAPI client (`custom_components/local_hikvision/isapi/`) is
Home-Assistant-free and independently testable:

```bash
# Protocol tests (no Home Assistant required)
uv run --no-project --with httpx --with respx --with pytest --with pytest-asyncio \
  python -m pytest tests -q

# Lint
uvx ruff check custom_components tests
```

The Home Assistant integration tests run under the HA test harness
(`pytest-homeassistant-custom-component`) in CI.

## License

Apache-2.0 (see the `SPDX-License-Identifier` headers on each source file).
