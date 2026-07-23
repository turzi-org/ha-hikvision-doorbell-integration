# SPDX-FileCopyrightText: 2026 Turzi
# SPDX-License-Identifier: Apache-2.0

"""Config flow for Turzi Local Hikvision."""

from __future__ import annotations

import functools
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant

from .const import (
    CONF_TIMEOUT,
    CONF_USE_TLS,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MAX_TIMEOUT,
    MIN_TIMEOUT,
)
from .isapi import (
    DeviceInfo,
    HikvisionAuthenticationError,
    HikvisionClient,
    HikvisionConnectionError,
    HikvisionError,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_USE_TLS, default=False): bool,
        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_TIMEOUT, max=MAX_TIMEOUT),
        ),
    },
)


async def _validate(
    hass: HomeAssistant,
    user_input: dict[str, Any],
) -> tuple[DeviceInfo | None, str | None]:
    """Connect with the given input and return (device_info, error_code).

    Building HikvisionClient constructs an httpx.AsyncClient, which performs
    blocking SSL-context setup — keep it off the event loop.
    """
    client = await hass.async_add_executor_job(
        functools.partial(
            HikvisionClient,
            user_input[CONF_HOST],
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
            port=user_input[CONF_PORT],
            use_tls=user_input[CONF_USE_TLS],
            timeout=user_input[CONF_TIMEOUT],
        ),
    )
    try:
        info = await client.get_device_info()
    except HikvisionAuthenticationError:
        return None, "invalid_auth"
    except HikvisionConnectionError:
        return None, "cannot_connect"
    except HikvisionError:
        return None, "unknown"
    else:
        return info, None
    finally:
        await client.aclose()


class HikvisionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the user-initiated config flow."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step: validate the connection and create the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            info, error = await _validate(self.hass, user_input)
            if error is not None:
                errors["base"] = error
            elif info is not None:
                await self.async_set_unique_id(info.serial_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info.device_name or info.model,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Let an existing entry's connection settings (e.g. timeout) be edited."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            info, error = await _validate(self.hass, user_input)
            if error is not None:
                errors["base"] = error
            elif info is not None:
                await self.async_set_unique_id(info.serial_number)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA,
                user_input or reconfigure_entry.data,
            ),
            errors=errors,
        )
