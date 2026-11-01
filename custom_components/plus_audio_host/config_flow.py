from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HostAuthError, HostClient, HostError
from .const import CONF_TOKEN, CONF_VERIFY_SSL, DOMAIN


def _schema(d: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_URL, default=d.get(CONF_URL, "http://")): str,
        vol.Required(CONF_TOKEN, default=d.get(CONF_TOKEN, "")): str,
        vol.Optional(CONF_VERIFY_SSL, default=d.get(CONF_VERIFY_SSL, False)): bool,
    })


async def _check(hass, data: dict) -> dict:
    url = data[CONF_URL].strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    c = HostClient(async_get_clientsession(hass, verify_ssl=data.get(CONF_VERIFY_SSL, False)), url, data[CONF_TOKEN].strip(),
                   data.get(CONF_VERIFY_SSL, False))
    st = await c.state()
    status = await c.status()
    # reads are open on the box, so check what the token is worth: staff is enough
    who = await c.whoami()
    if who.get("role") not in ("staff", "installer"):
        raise HostAuthError("that token isn't valid on this processor")
    dev = status.get("device") or {}
    return {"url": url, "name": st.get("device_name") or "Plus Audio Host", "serial": dev.get("serial") or status.get("host") or url}


class HostConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _check(self.hass, user_input)
            except HostAuthError:
                errors["base"] = "invalid_auth"
            except HostError:
                errors["base"] = "cannot_connect"
            except (KeyError, IndexError, TypeError):
                errors["base"] = "not_a_host"
            else:
                await self.async_set_unique_id(info["serial"])
                self._abort_if_unique_id_configured(updates={CONF_URL: info["url"], CONF_TOKEN: user_input[CONF_TOKEN].strip()})
                return self.async_create_entry(title=info["name"], data={CONF_URL: info["url"], CONF_TOKEN: user_input[CONF_TOKEN].strip(),
                                                                         CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, False)})
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}), errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN].strip()}
            try:
                await _check(self.hass, data)
            except HostAuthError:
                errors["base"] = "invalid_auth"
            except HostError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}), errors=errors)
