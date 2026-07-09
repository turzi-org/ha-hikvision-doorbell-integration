# Hikvision HA Integration — Implementation Plan

## 1. What this repo is

A **Home Assistant custom integration** for Hikvision door stations, mirroring the structure of the
existing `homeassistant-local-akuvox` integration: a thin `custom_components/` layer on top of a
separate **`pyhikvision` protocol library** (async ISAPI/HTTP, no binary SDK) where all device comms
live. First target device: **DS-KV9503-WBE1**.

It is the **per-brand driver** in the system — but "driver" here means *a HA integration exposing a
standard set of HA services + events*, not a headless Python library. The brand-agnostic
**`device-worker`** (separate repo, HA add-on) never talks to devices directly; it calls this
integration's **HA services** and listens to the **HA event bus**.

> This reverses two earlier drafts (HA integration with entities → headless driver library → **thin
> HA integration + protocol library, driven via HA services**). The pivot is because the Akuvox
> integration already proves this pattern works and exposes exactly the services the worker needs.

### System context

Three separate responsibilities on two planes. **Provisioning (write)** and **verification (read)**
are distinct services with different SLAs/scaling/blast-radius; they share only the DB.

```
CLOUD:  App → API → Backend → DB (source of truth) ───────► AUTH SERVER
                                     │                      (verification DECISION; exists)
                                     ▼                            ▲   │ allow/deny
                                 queue (per-device tasks)         │   │
EDGE (building's Home Assistant):    │                            │   │
  ┌─ HA ADD-ON(s), brand-agnostic ───┼────────────────────────────┼───┼──────────────┐
  │  (1) CREDENTIAL WORKER (write):  consume queue → HA services (add_user, …)         │
  │  (2) VERIFICATION BRIDGE (read): HA swipe event → auth server ┘   └► open relay    │
  │      (= NodeRED today; real-time; logically separate from the worker)              │
  └───────────────┬───────────────────────────────┬───────────────────────────────────┘
        HA services / event bus          HA services / event bus
                  │                               │
     ┌────────────▼─────────────┐   ┌─────────────▼─────────────┐
     │ local_akuvox integration │   │ hikvision integration     │ ← THIS REPO
     │  + pylocal-akuvox lib    │   │  + pyhikvision lib (ISAPI)│
     └────────────┬─────────────┘   └─────────────┬─────────────┘
                  ▼                               ▼
            Akuvox devices                  Hikvision devices
```

Roles: **(1) Credential worker** — write/async, queue → install/uninstall via HA services (+reconciler).
**(2) Verification bridge** — read/real-time edge glue, HA event → auth server → open relay (NodeRED
today). **(3) Auth server** — cloud decision authority, reads DB. (1) and (2) may share an add-on but
stay separate modules: provisioning must never add latency to, or be blocked by, verification.
This repo (Hikvision integration) is a dependency of **both** edge roles.

---

## 2. The cross-brand contract = standard HA services + event schema

The "driver interface" is a **canonical set of HA services and a normalized event vocabulary** that
every brand integration implements identically. Akuvox already defines ~90% of it (see its
`services.yaml`); this integration must match the same service names + field shapes so the worker is
brand-agnostic (it only needs each device's brand *domain*).

**Services to implement (match Akuvox shapes):**
- Users/credentials: `add_user`, `modify_user`, `delete_user`, `list_users`
  - fields incl. `name`, `user_id`, `schedules`, `private_pin` (PIN), `card_code` (NFC), + Hikvision
    face upload (new field, e.g. `face_image`).
- Schedules: `add_schedule`, `modify_schedule`, `delete_schedule`, `list_schedules`.
- Door open: via `lock.open` on the door/relay `lock` entities.
- (Assignment helpers as needed: `add_user_schedule_relay`, etc.)

**Event schema (normalized, fired on HA event bus like Akuvox's `EVENT_WEBHOOK_RECEIVED`):**
`valid_code_entered` (+code), `invalid_code_entered`, `valid_card_entered` (+card_sn),
`valid_face_recognition`, relay/input triggered/closed, tamper, door-open-timeout, call events.

> Aligning field names across brands is the main contract work. Where Hikvision's model differs
> (employeeNo, right-plan templates, FDLib face), map internally so the *service surface* stays
> uniform.

---

## 3. Credential validity model — Hybrid (remote verification is real & in production)

**Correction over an earlier draft:** Akuvox action URLs *do* pass the entered code on
`invalid_code_entered` (the integration's `_URL_TEMPLATES` omits `&code=$code` — see §5 note — but the
device is configured to send it). So an *un-enrolled* PIN is fully brokerable. This pattern is
**already in production on Akuvox** via NodeRED:

```
unknown PIN typed → device fires invalid_code_entered + &code=XXXX
   → HA webhook → NodeRED → cloud auth server (reads DB, decides allow/deny)
   → back to HA → open relay (or not)
```

The PIN is valid the instant it is committed to the cloud DB — **before any local enrollment** —
because an unknown PIN still round-trips to the cloud with its code. That IS the instant-usability
guarantee.

**Target = Hybrid (both paths, already the operating reality):**

| | **Remote verification (existing)** | **Local enrollment (new — what we're building)** |
|---|---|---|
| Provides | Instant usability, from cloud DB | Offline capability, low latency, less cloud dependence |
| Decision authority | Cloud auth server (reads DB) | The device (once the credential is installed) |
| Path | device → HA event → broker → cloud → open relay | app → API → DB → queue → worker → `<brand>.add_user` |
| Needs online | device + HA + cloud at entry time | nothing at entry (device grants locally) |

- **The two original requirements map exactly:** "write a PIN with schedule" = local enrollment (new);
  "instantly usable even if the device doesn't have it yet" = remote verification (existing).
- The queue/worker does **not** provide instant-ness — remote verification already does. The queue
  makes PINs work **locally/offline** over time and cuts per-entry cloud round-trips.
- Broker/decision authority stays in the **cloud auth server** (today reached via NodeRED). At the
  edge, whoever relays the event + open command is just plumbing (NodeRED today; could be the
  integration's event bus + the worker tomorrow — see §5).

**Hikvision replicates the trick ONLY for cards — resolved via SDK event structs (§8):**

| Credential | Instant remote-verification on Hikvision | Consequence |
|---|---|---|
| **Card/NFC** | ✅ yes — `MINOR_INVALID_CARD` (0x09) event carries `cardNo` even when unregistered | Full Hybrid: instant remote-verify + local enrollment. Parity with Akuvox card flow. |
| **PIN** | ⚠️ device stores **no per-user PIN** (live UserInfo records have no PIN field; `unlockPassword` is global). Passive ACS event also has no entered-PIN. | **Neither passive brokering nor local per-user enrollment works.** Per-resident PINs are only possible via **native remote verification** (`AcsCfg`/`remoteCheck`) — validate on non-prod. Otherwise Hikvision PINs are global-only. |
| **Face** | ❌ no (inherent — a face isn't a server-verifiable value) | Local-enrollment only. Plus no face search → reconcile from DB (§8.5). |

So on Hikvision the validity model is **per-credential**: cards = Hybrid; PIN/face = local-enrollment.
This is exactly the fork in the original requirement ("if instant isn't possible, make the user wait
until installed") — for Hikvision PINs, it's the wait-for-install branch. Card verification can use the
brokered invalid-card event, or possibly a native platform-verify mode (`0x32`) — worth a follow-up
config probe, but brokering already works.

---

## 4. Hikvision integration internals

### 4.1 Structure (mirror `homeassistant-local-akuvox`)
```
custom_components/hikvision_doorbell/
├── __init__.py, manifest.json (requirements: pyhikvision>=x)
├── config_flow.py           # host/port/creds; validate via deviceInfo
├── coordinator.py           # DataUpdateCoordinator: relay/door status, user cache
├── lock.py / switch.py      # door relays (lock.open = pulse)
├── binary_sensor.py         # door contact, tamper, inputs
├── event.py                 # HA event entities from device events
├── number.py / button.py    # as needed
├── services.yaml + services # add_user/schedule/… matching the contract (§2)
├── events transport         # alertStream consumer OR HTTP-host webhook → HA event bus
└── const.py, strings.json, translations/
```

### 4.2 `pyhikvision` protocol library (new, separate package)
Async ISAPI client (aiohttp + digest) with the device operations the integration calls:
`get_info`, `get_relay_status`, `open_door`, `door_state`, `add_user`(+PIN/schedule),
`add_card`, `add_face`, `delete_user`, `list_users`, `list_schedules`, event stream/parse.
This is where the ISAPI endpoint contract (below) is implemented.

### 4.3 ISAPI endpoint contract (implemented in the library)
- Identify: `GET /ISAPI/System/deviceInfo`, `…/capabilities`.
- Door open: `PUT /ISAPI/AccessControl/RemoteControl/door/{id}` `<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>`.
- Door/input state: alertStream `AccessControllerEvent` / `…/Door/status` / IO inputs.
- Users/PIN: `POST /ISAPI/AccessControl/UserInfo/Record` (`password`=PIN, `Valid`, `RightPlan`);
  schedules via `UserRightWeekPlanCfg` + `UserRightPlanTemplate`.
- Card/NFC: `POST /ISAPI/AccessControl/CardInfo/Record`.
- Face: `POST /ISAPI/Intelligent/FDLib/FaceDataRecord` (multipart JSON + JPEG).
- Events: `GET /ISAPI/Event/notification/alertStream` (multipart) OR configure device HTTP-host
  notifications to a HA webhook (mirrors Akuvox's webhook model — likely the more consistent choice).

---

## 5. Event transport + the remote-verification routing fork

**DECIDED (live probe of real KV9503, fw V2.3.13):** Hikvision does **NOT** support Akuvox-style
device→webhook push — `Event/notification/httpHosts` = `notSupport`, `Event/triggers` only offers the
`center` method (no HTTP host). So the integration **must run a persistent `alertStream` consumer**
(`GET /ISAPI/Event/notification/alertStream`, multipart/mixed JSON) and re-emit the **same normalized
bus events** the worker/bridge expect. Access events arrive as **`AccessControllerEvent`**
(majorEventType/subEventType/deviceNo). This diverges from Akuvox's webhook transport but keeps the
normalized event-bus abstraction intact — the worker still sees one schema regardless of brand.
(Akuvox = device pushes webhook; Hikvision = integration pulls alertStream. Same output.)

**Open fork — where remote verification runs.** Today the production flow runs *outside* the Akuvox
integration: the integration's `_URL_TEMPLATES["InvalidCodeEntered"]` omits `&code=$code`
(webhook.py:68) and its handler only resolves a user on `valid_code_entered` (webhook.py:273). The
working invalid-PIN→cloud path uses **separately-configured device action URLs + NodeRED**. Decide:
- **(A) Route through the integration (recommended for a brand-agnostic worker):** enhance the Akuvox
  integration to include the code on `invalid_code_entered` and surface it on the event bus; Hikvision
  emits the same normalized "unknown credential attempted" event. The broker (worker or NodeRED) then
  consumes one uniform schema across brands. Requires a change to the Akuvox integration.
- **(B) Keep NodeRED + out-of-band action URLs.** No integration change, but the remote-verification
  path stays brand-specific and separate from the normalized event bus.

---

## 6. Milestones

**M0 — `pyhikvision` skeleton + connect.** Async ISAPI client (digest, retries); `get_info`,
`get_relay_status`, capability probe. Tests vs recorded fixtures.

**M1 — HA integration skeleton.** config_flow, coordinator, `lock`/`binary_sensor` entities
(door open + state). Mirror Akuvox structure.

**M2 — Credential services.** `add_user`(+PIN/schedule), `add_card`, face upload, `add_schedule`,
list/modify/delete — matching the Akuvox service contract (§2). This is the core new value.

**M3 — Events → HA bus.** Webhook (preferred) or alertStream consumer; emit the normalized event
schema. Enables the worker's verification/automation layer.

**M4 — Contract alignment + harden.** Reconcile service/field names with Akuvox; diagnostics;
reconnect/backoff; docs; packaging (`pyhikvision` to PyPI, integration to HACS).

---

## 7. Cross-repo work (with `device-worker` + Akuvox)

- **Freeze the canonical HA service + event schema** across Akuvox + Hikvision (the real contract).
  Decide where brand field-mapping differences are absorbed (inside each integration).
- **Credential worker** (write plane): discovers a device's brand domain to pick the service
  namespace; per-device-FIFO task consumption; status callbacks to the backend; reconciler. Does NOT
  make verification decisions.
- **Verification bridge** (read plane, = NodeRED today): HA swipe event → auth server → open relay.
  Separate module from the worker (shared add-on OK). The **auth server** (cloud, existing) remains
  the decision authority; the edge only relays.
- Auth token/permissions for the edge (HA long-lived token) to call services + read the event bus.

### 7.1 Offline resilience — local edge DB (open design area)

Proposal (lean: adopt): keep a **per-building local DB = a read-replica of that building's
desired-state** (credentials/grants/schedules), so the building keeps working when the internet is
down (and faster when it's up).

- **Read-mostly / one-way-ish sync:** desired-state cloud→building (down); events/audit building→cloud
  (up). Cloud DB stays global source of truth; no local credential creation → no multi-master.
- **Serves both edge roles:** verification bridge decides locally (offline + no cloud round-trip);
  credential worker reconciles devices against the local DB instead of depending on the cloud queue.
- **May be MANDATORY, not optional:** devices have finite user/PIN/card/face storage. If a building
  has more users than a door can hold, edge verification is *required*, and you can't fall back to
  "everyone enrolled on-device" during an outage → the local DB is the only thing keeping the door
  working offline. Decided by **device capacity limits** (measure — see §8).
- **Hard parts to respect:** (1) revocation is a security window — prioritize revocations in sync,
  set an acceptable lag; (2) offline decisions need the *same* decision logic as the cloud auth
  server — share it as a library or accept degraded offline; (3) sync must be a versioned change-feed
  with catch-up on reconnect (handle edge-offline-during-change); (4) fail-open vs fail-closed policy
  when even the local DB is stale/unreachable.
- **Scope:** lives in the edge-service/worker repo + cloud. Does NOT affect this repo (the Hikvision
  integration still only exposes services + events + open).
- **Resilience tiers to choose:** (T1) device-local only, no edge DB — offline = only on-device
  credentials work; (T2) edge DB + bridge decision logic — offline verification parity for the whole
  building dataset. Choice gated on capacity (§8).

---

### 7.2 Repo & build allocation (post-investigation of turzi-apps + turzi-bridge)

The cloud + transport already exist; only **one new repo** is needed. Build allocation:

| Piece | Home | New repo? |
|---|---|---|
| Hikvision ISAPI protocol lib `pyhikvision` | new package (mirrors `pylocal-akuvox`) | **YES — only one** |
| Hikvision HA integration | this repo | exists |
| Auth-server decision, DB, remote-open | `turzi-apps/api-v2` (`/access/validate`, `pins`, `devices`) | exists |
| Credential-sync **worker** (queue, per-device FIFO, status, retry, reconcile) | **new module in `api-v2`** + brand wiring | no (extend) |
| Cloud↔HA transport (service calls + events) | `turzi-bridge` (Turzi Protocol / MQTT) | exists |
| Command/event **contract** | **extend Turzi Protocol `PROTOCOL.md`** (access-control commands + swipe events) | no |
| **Verification bridge** (swipe → `/access/validate` → open) | ride bridge rails, replace NodeRED | no |
| Local edge DB (offline / §7.1 T2) | future edge-side component | deferred |

Notes:
- `api-v2` already models sync (`/devices/:id/sync`, "pending sync operations", auto-retry) but the
  worker/queue is **not implemented** yet, and there is **no Hikvision/Akuvox brand wiring** yet — that
  is the real cloud-side work.
- The bridge command payload is `{command:"{domain}.{action}", parameters, metadata}` → executed as an
  arbitrary HA service call. Confirm it will carry access-control commands (e.g. `hikvision.add_user`
  with structured params) and forward non-entity **swipe events** for verification — those two may need
  small bridge extensions.
- Worker home = `api-v2` (owns DB/sync state), **not** a separate HA add-on. Caveat: offline/T2 may
  later require an edge-side sync executor + local DB.

---

## 8. Risks / verification status (live-probed real DS-KV9503-WBE1, fw V2.3.13)

1. ~~**Event transport.**~~ **RESOLVED:** no webhook/httpHosts support → use **alertStream** consumer
   (§5). `AccessControllerEvent` is the carrier.
2. **Remote verification — two paths (partly resolved):**
   - **Passive brokering (confirmed):** unregistered **card** → `MINOR_INVALID_CARD`(0x09) event with
     `cardNo` → broker → open. Cards get instant verify with no device config change. **PIN not
     brokerable this way** (no entered-PIN in any ACS event).
   - **Native remote verification (ISAPI §12.12) — device supports it** (`isSupportRemoteCheck:true`),
     could cover PIN + unregistered, restoring instant-PIN. BUT this fw (V2.3.13) exposes only a coarse
     `AcsCfg` (`remoteCheckDoorEnabled` on/off + `remoteCheckTimeout`), so PIN/user-type granularity is
     UNCONFIRMED. **Testing requires enabling it — production-risky on a live door (5s-timeout lockout);
     validate only on a test unit / maintenance window with a stub approve-platform + offline fallback.**
     Endpoints: `PUT /ISAPI/AccessControl/AcsCfg`, `PUT /ISAPI/AccessControl/remoteCheck`.
3. ~~**Capacity.**~~ **RESOLVED:** 20000 users / 100000 cards / 20000 faces → everyone fits on-device for
   realistic buildings. Local edge DB is resilience/latency, not capacity-mandatory → **T1 viable**.
4. **PIN storage field (open).** UserInfo capabilities show no explicit `password`/PIN field (has
   `dynamicCode` 4–8, `Valid`, employeeNo). Confirm how keypad PIN is stored via a test-user write
   (likely `password` in the UserInfo record).
5. **Face reconciliation gap (new).** FDLib `isSuportFDSearch:false` → cannot list/search enrolled
   faces → reconciler can't diff device faces vs desired-state. Track face state authoritatively
   in the DB; treat device as write-only for faces.
6. **Endpoint/field variance.** Confirm each write path (`UserInfo/Record`, `CardInfo/Record`,
   `FaceDataRecord`) against a test user before shipping.
7. **Face upload shape.** `FDLib/FaceDataRecord` multipart (JSON + JPEG), `faceLibType:blackFD`, FDID single lib.
6. **Auth/privilege.** Digest vs basic; account privilege for AccessControl writes.

---

## 9. Reference reuse map

| Need | Reference | Reuse |
|------|-----------|-------|
| Integration structure, services, webhook, coordinator | `reference/homeassistant-local-akuvox` | **primary template** — mirror it for Hikvision |
| Canonical service/field shapes | akuvox `services.yaml` + `specs/003-schedule-user-services` | the contract to match |
| Event vocabulary | akuvox `webhook.py` `_URL_TEMPLATES` | normalized event schema |
| Door open ISAPI, relay ctrl, capability probe | `reference/Hikvision-Addons` `doorbell.py`, `ISAPI.md` | ISAPI endpoints for the pyhikvision lib |
| SDK field lookups | `Hikvision-Addons/.../Device Network SDK.pdf` | endpoint/field details |

The Akuvox integration is now the **primary architectural template**; the Hikvision-Addons repo is the
**ISAPI endpoint reference** for the protocol library.
