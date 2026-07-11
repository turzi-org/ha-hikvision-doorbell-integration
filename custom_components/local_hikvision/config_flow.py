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

from .const import CONF_USE_TLS, DEFAULT_PORT, DOMAIN
from .isapi import (
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
    },
)


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
            # Building HikvisionClient constructs an httpx.AsyncClient, which
            # performs blocking SSL-context setup — keep it off the event loop.
            client = await self.hass.async_add_executor_job(
                functools.partial(
                    HikvisionClient,
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    port=user_input[CONF_PORT],
                    use_tls=user_input[CONF_USE_TLS],
                ),
            )
            try:
                info = await client.get_device_info()
            except HikvisionAuthenticationError:
                errors["base"] = "invalid_auth"
            except HikvisionConnectionError:
                errors["base"] = "cannot_connect"
            except HikvisionError:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info.serial_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info.device_name or info.model,
                    data=user_input,
                )
            finally:
                await client.aclose()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
