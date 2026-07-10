# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Async ISAPI client for Hikvision door stations.

Transport decision (revisit if needed): this uses ``httpx.AsyncClient`` for its
built-in async HTTP Digest auth. If we later want to align with Home Assistant's
``aiohttp`` stack we can swap the transport behind this same public surface.
"""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET  # noqa: S405 - responses are from an authenticated LAN device
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Self

import httpx

from .errors import (
    HikvisionAuthenticationError,
    HikvisionConnectionError,
    HikvisionParseError,
    HikvisionResponseError,
)
from .events import iter_stream_events
from .models import (
    AcsConfig,
    Capabilities,
    Card,
    DeviceEvent,
    DeviceInfo,
    Person,
    UserCount,
)

_DEFAULT_TIMEOUT = 10.0


def _raise_for_isapi_error(data: dict[str, Any], path: str) -> None:
    """Raise if a parsed ISAPI JSON response is an error envelope.

    Success payloads either omit ``statusCode`` or set it to ``1``. Anything
    else (e.g. ``badJsonContent``, ``notSupport``) is surfaced as an error.

    Args:
        data: Parsed JSON response.
        path: The request path, for the error message.

    Raises:
        HikvisionResponseError: If ``statusCode`` is present and not ``1``.

    """
    code = data.get("statusCode")
    if code is not None and code != 1:
        raise HikvisionResponseError(
            f"{path}: {data.get('statusString')} "
            f"({data.get('subStatusCode')}/{data.get('errorMsg')})",
        )


class HikvisionClient:
    """Talk to a single Hikvision device over ISAPI/HTTP.

    Use as an async context manager::

        async with HikvisionClient("10.0.0.5", "admin", "secret") as client:
            info = await client.get_device_info()
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 80,
        use_tls: bool = False,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the client.

        Args:
            host: Device IP or hostname.
            username: ISAPI account username.
            password: ISAPI account password.
            port: HTTP(S) port (default 80).
            use_tls: Use ``https`` instead of ``http``.
            timeout: Per-request timeout in seconds.

        """
        scheme = "https" if use_tls else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            auth=httpx.DigestAuth(username, password),
            timeout=timeout,
            verify=use_tls,
        )

    async def __aenter__(self) -> Self:
        """Enter the async context, returning ``self``."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the underlying HTTP client on context exit."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        content: str | bytes | None = None,
        content_type: str | None = None,
    ) -> str:
        """Perform an ISAPI request and return the response body as text.

        Args:
            method: HTTP method (GET, PUT, POST, DELETE).
            path: ISAPI path beginning with ``/ISAPI``.
            content: Optional request body.
            content_type: Value for the ``Content-Type`` header. Required by the
                device for JSON/XML bodies — without it ISAPI returns
                ``badJsonContent``.

        Returns:
            The response body decoded as text.

        Raises:
            HikvisionAuthenticationError: On HTTP 401.
            HikvisionConnectionError: On network/timeout failures.
            HikvisionResponseError: On other non-2xx responses.

        """
        headers = {"Content-Type": content_type} if content_type else None
        try:
            response = await self._client.request(
                method,
                path,
                content=content,
                headers=headers,
            )
        except httpx.TimeoutException as err:
            raise HikvisionConnectionError(f"Timeout calling {path}") from err
        except httpx.TransportError as err:
            raise HikvisionConnectionError(f"Cannot reach {path}: {err}") from err

        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise HikvisionAuthenticationError(f"Unauthorized calling {path}")
        if not response.is_success:
            raise HikvisionResponseError(
                f"{method} {path} returned HTTP {response.status_code}",
            )
        return response.text

    async def get_device_info(self) -> DeviceInfo:
        """Fetch device identity from ``/ISAPI/System/deviceInfo``.

        Returns:
            Parsed :class:`DeviceInfo`.

        Raises:
            HikvisionParseError: If the response XML is missing expected nodes.

        """
        body = await self._request("GET", "/ISAPI/System/deviceInfo")
        try:
            root = ET.fromstring(body)  # noqa: S314 - authenticated LAN device response
        except Exception as err:  # noqa: BLE001 - ElementTree raises broadly
            raise HikvisionParseError("Malformed deviceInfo XML") from err

        def _text(tag: str) -> str:
            """Return the text of a namespaced child tag, or ``""``."""
            node = root.find(f"{{*}}{tag}")
            return node.text or "" if node is not None and node.text else ""

        serial = _text("serialNumber")
        model = _text("model")
        if not serial or not model:
            raise HikvisionParseError("deviceInfo missing serialNumber/model")

        return DeviceInfo(
            model=model,
            serial_number=serial,
            firmware_version=_text("firmwareVersion"),
            device_name=_text("deviceName"),
            device_type=_text("deviceType"),
            mac_address=_text("macAddress"),
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform a JSON ISAPI request and return the parsed response.

        Args:
            method: HTTP method.
            path: ISAPI path (should include ``?format=json``).
            body: Optional JSON request body.

        Returns:
            The parsed JSON response.

        Raises:
            HikvisionParseError: If the response is not valid JSON.
            HikvisionResponseError: If the device returns an ISAPI error envelope.

        """
        content = json.dumps(body) if body is not None else None
        content_type = "application/json" if content is not None else None
        text = await self._request(
            method,
            path,
            content=content,
            content_type=content_type,
        )
        try:
            data: dict[str, Any] = json.loads(text) if text else {}
        except json.JSONDecodeError as err:
            raise HikvisionParseError(f"Non-JSON response from {path}") from err
        _raise_for_isapi_error(data, path)
        return data

    # ----- persons / users -------------------------------------------------

    async def get_user_count(self) -> UserCount:
        """Return enrollment counts (``/ISAPI/AccessControl/UserInfo/Count``)."""
        data = await self._request_json(
            "GET",
            "/ISAPI/AccessControl/UserInfo/Count?format=json",
        )
        c = data.get("UserInfoCount", {})
        return UserCount(
            users=int(c.get("userNumber", 0)),
            faces=int(c.get("bindFaceUserNumber", 0)),
            cards=int(c.get("bindCardUserNumber", 0)),
        )

    @staticmethod
    def _user_body(person: Person) -> dict[str, Any]:
        """Build the ISAPI ``UserInfo`` object from a :class:`Person`."""
        user: dict[str, Any] = {
            "employeeNo": person.employee_no,
            "name": person.name,
            "userType": person.user_type,
        }
        if person.validity is not None:
            user["Valid"] = person.validity.to_isapi()
        if person.floor_number is not None:
            user["floorNumber"] = person.floor_number
        if person.room_number is not None:
            user["roomNumber"] = person.room_number
        return {"UserInfo": user}

    async def add_user(self, person: Person) -> None:
        """Enroll a person via ``POST /ISAPI/AccessControl/UserInfo/Record``.

        Builds the ``UserInfo`` record from the fields this device's
        ``UserInfo/capabilities`` exposes. Door rights/schedules are NOT set
        here — assign them separately by ``employee_no`` (``UserRightWeekPlanCfg``).

        Args:
            person: The person to enroll.

        """
        await self._request_json(
            "POST",
            "/ISAPI/AccessControl/UserInfo/Record?format=json",
            body=self._user_body(person),
        )

    async def modify_user(self, person: Person) -> None:
        """Edit an existing person via ``PUT /ISAPI/AccessControl/UserInfo/Modify``."""
        await self._request_json(
            "PUT",
            "/ISAPI/AccessControl/UserInfo/Modify?format=json",
            body=self._user_body(person),
        )

    async def search_users(
        self,
        *,
        position: int = 0,
        max_results: int = 30,
        search_id: str = "pylocal-hikvision",
    ) -> list[Person]:
        """List enrolled persons via ``POST /ISAPI/AccessControl/UserInfo/Search``.

        Used for reconciliation. NOTE: the exact request body still needs
        non-production validation (a naive body returned ``badJsonContent`` on
        the live device); ``max_results`` is capped at 30 by this device.

        Args:
            position: Result offset for pagination.
            max_results: Page size (device max 30).
            search_id: Opaque search session id.

        Returns:
            The page of persons.

        """
        data = await self._request_json(
            "POST",
            "/ISAPI/AccessControl/UserInfo/Search?format=json",
            body={
                "UserInfoSearchCond": {
                    "searchID": search_id,
                    "searchResultPosition": position,
                    "maxResults": max_results,
                },
            },
        )
        result = data.get("UserInfoSearch", {})
        people: list[Person] = []
        for u in result.get("UserInfo", []):
            people.append(  # noqa: PERF401 - explicit for readability
                Person(
                    employee_no=str(u.get("employeeNo", "")),
                    name=str(u.get("name", "")),
                    user_type=str(u.get("userType", "normal")),
                    floor_number=u.get("floorNumber"),
                    room_number=u.get("roomNumber"),
                    # validity round-trip (parse Valid -> Validity) deferred.
                    validity=None,
                ),
            )
        return people

    async def delete_user(self, employee_no: str) -> None:
        """Delete a person (and their linked credentials) by employee number."""
        await self._request_json(
            "PUT",
            "/ISAPI/AccessControl/UserInfo/Delete?format=json",
            body={"UserInfoDelCond": {"EmployeeNoList": [{"employeeNo": employee_no}]}},
        )

    # ----- cards -----------------------------------------------------------

    async def add_card(self, card: Card) -> None:
        """Enroll a card/tag via ``POST /ISAPI/AccessControl/CardInfo/Record``."""
        await self._request_json(
            "POST",
            "/ISAPI/AccessControl/CardInfo/Record?format=json",
            body={
                "CardInfo": {
                    "employeeNo": card.employee_no,
                    "cardNo": card.card_no,
                    "cardType": card.card_type,
                },
            },
        )

    async def delete_card(self, employee_no: str) -> None:
        """Delete the card(s) linked to a person by employee number."""
        await self._request_json(
            "PUT",
            "/ISAPI/AccessControl/CardInfo/Delete?format=json",
            body={"CardInfoDelCond": {"EmployeeNoList": [{"employeeNo": employee_no}]}},
        )

    async def search_cards(
        self,
        *,
        position: int = 0,
        max_results: int = 30,
        search_id: str = "pylocal-hikvision",
    ) -> list[Card]:
        """List enrolled cards via ``POST /ISAPI/AccessControl/CardInfo/Search``.

        For reconciliation. Body format flagged for non-production validation.

        Args:
            position: Result offset for pagination.
            max_results: Page size (device max 30).
            search_id: Opaque search session id.

        Returns:
            The page of cards.

        """
        data = await self._request_json(
            "POST",
            "/ISAPI/AccessControl/CardInfo/Search?format=json",
            body={
                "CardInfoSearchCond": {
                    "searchID": search_id,
                    "searchResultPosition": position,
                    "maxResults": max_results,
                },
            },
        )
        result = data.get("CardInfoSearch", {})
        return [
            Card(
                employee_no=str(c.get("employeeNo", "")),
                card_no=str(c.get("cardNo", "")),
                card_type=str(c.get("cardType", "normalCard")),
            )
            for c in result.get("CardInfo", [])
        ]

    # ----- face ------------------------------------------------------------

    async def add_face(
        self,
        employee_no: str,
        image_jpeg: bytes,
        *,
        fdid: str = "1",
    ) -> None:
        """Enroll a face picture, linked to a person by ``employee_no``.

        Uses ``POST /ISAPI/Intelligent/FDLib/FaceDataRecord`` as multipart
        (JSON metadata part + JPEG). NOTE: multipart part naming is device
        -specific — validate on a non-production device (this device's FDLib is
        ``faceLibType=blackFD``, single library, ``post`` only, no face search).

        Args:
            employee_no: The person the face belongs to (``FPID``).
            image_jpeg: JPEG image bytes.
            fdid: Face library ID (single library on this device).

        """
        meta = {"faceLibType": "blackFD", "FDID": fdid, "FPID": employee_no}
        files: dict[str, tuple[str | None, str | bytes, str]] = {
            "FaceDataRecord": (None, json.dumps(meta), "application/json"),
            "FaceImage": ("face.jpg", image_jpeg, "image/jpeg"),
        }
        response = await self._client.request(
            "POST",
            "/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json",
            files=files,
        )
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise HikvisionAuthenticationError("Unauthorized uploading face")
        if not response.is_success:
            raise HikvisionResponseError(
                f"Face upload returned HTTP {response.status_code}",
            )
        try:
            _raise_for_isapi_error(response.json(), "FaceDataRecord")
        except json.JSONDecodeError as err:
            raise HikvisionParseError("Non-JSON face upload response") from err

    # ----- door control ----------------------------------------------------

    async def open_door(self, door_no: int, *, cmd: str = "open") -> None:
        """Actuate a door relay via ``PUT /ISAPI/AccessControl/RemoteControl/door``.

        Args:
            door_no: 1-based door number (this device has doors 1..2).
            cmd: One of ``open``, ``close``, ``alwaysOpen``, ``resume``.

        """
        body = f"<RemoteControlDoor><cmd>{cmd}</cmd></RemoteControlDoor>"
        await self._request(
            "PUT",
            f"/ISAPI/AccessControl/RemoteControl/door/{door_no}",
            content=body,
            content_type="application/xml",
        )

    # ----- capabilities ----------------------------------------------------

    async def get_capabilities(self) -> Capabilities:
        """Probe the device and summarize its access-control capabilities.

        Each probe is best-effort: an unsupported endpoint leaves the
        corresponding field ``None`` rather than failing the whole call.

        Returns:
            The populated :class:`Capabilities`.

        """
        door_count = await self._probe_door_count()
        remote_check = await self._probe_remote_check()
        max_users = await self._probe_json_int(
            "/ISAPI/AccessControl/UserInfo/capabilities?format=json",
            ("UserInfo", "maxRecordNum"),
        )
        max_cards = await self._probe_json_int(
            "/ISAPI/AccessControl/CardInfo/capabilities?format=json",
            ("CardInfo", "maxRecordNum"),
        )
        max_faces = await self._probe_json_int(
            "/ISAPI/Intelligent/FDLib/capabilities?format=json",
            ("FDRecordDataMaxNum",),
        )
        return Capabilities(
            door_count=door_count,
            supports_pin=None,  # dynamicCode role unconfirmed on this VIS device
            supports_card=max_cards is not None,
            supports_face=max_faces is not None,
            # Cards report cardNo even when unregistered (brokerable); PINs do not.
            reports_attempted_credential=True,
            supports_remote_check=remote_check,
            max_users=max_users,
            max_cards=max_cards,
            max_faces=max_faces,
        )

    async def _probe_door_count(self) -> int | None:
        """Best-effort read of the door count from door capabilities."""
        try:
            xml = await self._request(
                "GET",
                "/ISAPI/AccessControl/RemoteControl/door/capabilities",
            )
            node = ET.fromstring(xml).find("{*}doorNo")  # noqa: S314 - authenticated LAN device response
        except Exception:  # noqa: BLE001 - best-effort probe
            return None
        if node is not None and "max" in node.attrib:
            return int(node.attrib["max"])
        return None

    async def _probe_remote_check(self) -> bool | None:
        """Best-effort read of native remote-verification support."""
        try:
            xml = await self._request("GET", "/ISAPI/AccessControl/capabilities")
        except Exception:  # noqa: BLE001 - best-effort probe
            return None
        node = ET.fromstring(xml).find("{*}isSupportRemoteCheck")  # noqa: S314 - authenticated LAN device response
        if node is None or node.text is None:
            return None
        return bool(node.text.strip().lower() == "true")

    async def _probe_json_int(
        self,
        path: str,
        keys: tuple[str, ...],
    ) -> int | None:
        """Best-effort read of a nested integer from a JSON capability endpoint."""
        try:
            data: Any = await self._request_json("GET", path)
        except (HikvisionResponseError, HikvisionParseError, HikvisionConnectionError):
            return None
        for key in keys:
            if not isinstance(data, dict) or key not in data:
                return None
            data = data[key]
        return int(data) if isinstance(data, int) else None

    # ----- events ----------------------------------------------------------

    async def stream_events(self) -> AsyncIterator[DeviceEvent]:
        """Yield events from the long-lived ``alertStream`` connection.

        Opens ``GET /ISAPI/Event/notification/alertStream`` and parses the
        multipart/mixed JSON parts (``AccessControllerEvent`` etc.) into
        :class:`DeviceEvent`. The generator runs until the caller stops iterating
        or the connection drops (reconnect/backoff is the caller's concern).

        Yields:
            Parsed events as they arrive.

        Raises:
            HikvisionConnectionError: If the stream cannot be established.

        """
        try:
            async with self._client.stream(
                "GET",
                "/ISAPI/Event/notification/alertStream",
            ) as response:
                if response.status_code == httpx.codes.UNAUTHORIZED:
                    raise HikvisionAuthenticationError("Unauthorized on alertStream")
                if not response.is_success:
                    raise HikvisionResponseError(
                        f"alertStream returned HTTP {response.status_code}",
                    )
                boundary = _parse_boundary(response.headers.get("content-type", ""))
                async for event in iter_stream_events(
                    response.aiter_bytes(),
                    boundary,
                ):
                    yield event
        except httpx.TransportError as err:
            raise HikvisionConnectionError(f"alertStream failed: {err}") from err

    async def stream_events_reconnecting(
        self,
        *,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> AsyncIterator[DeviceEvent]:
        """Yield events forever, reconnecting with exponential backoff on drop.

        The raw ``stream_events`` ends when the connection drops; this wrapper
        reconnects, resetting the backoff after any successful event. Runs until
        the caller stops iterating (or is cancelled).

        Args:
            base_backoff: Initial delay (seconds) after a failure.
            max_backoff: Ceiling for the backoff delay.

        Yields:
            Parsed events across reconnections.

        """
        backoff = base_backoff
        while True:
            try:
                async for event in self.stream_events():
                    backoff = base_backoff
                    yield event
            except (HikvisionConnectionError, HikvisionResponseError):
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    # ----- access-control config (remote verification) ---------------------

    async def get_acs_config(self) -> AcsConfig:
        """Read the native remote-verification config from ``AcsCfg``."""
        data = await self._request_json(
            "GET",
            "/ISAPI/AccessControl/AcsCfg?format=json",
        )
        cfg = data.get("AcsCfg", {})
        return AcsConfig(
            remote_check_enabled=bool(cfg.get("remoteCheckDoorEnabled", False)),
            remote_check_timeout=int(cfg.get("remoteCheckTimeout", 5)),
        )

    async def set_remote_check(
        self,
        *,
        enabled: bool,
        timeout: int | None = None,
    ) -> None:
        """Enable/disable native remote verification (``PUT /AccessControl/AcsCfg``).

        DANGER — behavior-changing on a live door: when enabled, the device
        defers entry decisions to the platform; if nothing answers within
        ``remote_check_timeout`` seconds, entries FAIL (people are locked out).
        Only call against a non-production device or in a controlled window with
        a responding verifier. This helper does not guard against that.

        Args:
            enabled: Whether to enable remote verification.
            timeout: Optional remote-check timeout in seconds (device range 1-10).

        """
        cfg: dict[str, Any] = {"remoteCheckDoorEnabled": enabled}
        if timeout is not None:
            cfg["remoteCheckTimeout"] = timeout
        await self._request_json(
            "PUT",
            "/ISAPI/AccessControl/AcsCfg?format=json",
            body={"AcsCfg": cfg},
        )


def _parse_boundary(content_type: str) -> str:
    """Extract the MIME boundary token from a ``multipart/*`` Content-Type."""
    for token in content_type.split(";"):
        token = token.strip()
        if token.startswith("boundary="):
            return token[len("boundary=") :].strip('"')
    return "MIME_boundary"
