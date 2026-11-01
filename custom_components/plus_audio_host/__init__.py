"""Plus Audio Host: zones as media players, scenes, announcements, engine health (local API, no cloud)."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HostClient, HostError
from .const import CONF_TOKEN, CONF_VERIFY_SSL, DOMAIN
from .coordinator import HostCoordinator

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SELECT, Platform.SENSOR]

ANNOUNCE_SCHEMA = vol.Schema({
    vol.Optional("config_entry_id"): cv.string,
    vol.Optional("message"): cv.string,          # a saved message, by name
    vol.Optional("text"): cv.string,             # or text the box speaks
    vol.Optional("zones", default=[]): vol.All(cv.ensure_list, [cv.string]),   # zone names or numbers; empty = the box's default
    vol.Optional("chime"): cv.boolean,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = HostClient(async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, False)),
                        entry.data[CONF_URL], entry.data[CONF_TOKEN], entry.data.get(CONF_VERIFY_SSL, False))
    coord = HostCoordinator(hass, client)
    await coord.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, "announce"):
        async def announce(call: ServiceCall) -> None:
            coords: dict = hass.data.get(DOMAIN, {})
            eid = call.data.get("config_entry_id")
            targets = [coords[eid]] if eid in coords else list(coords.values())
            if eid and eid not in coords:
                raise HomeAssistantError("no such Plus Audio Host")
            for c in targets:
                msg_id = None
                if call.data.get("message"):
                    name = call.data["message"].strip().lower()
                    msgs = (c.data.get("messages") or {}).get("messages", [])
                    hit = next((m for m in msgs if m["name"].lower() == name), None)
                    if not hit:
                        raise HomeAssistantError(f"no saved message called {call.data['message']}")
                    msg_id = hit["id"]
                elif not call.data.get("text"):
                    raise HomeAssistantError("give a message (saved on the box) or text")
                zones = []
                for z in call.data.get("zones", []):
                    zs = c.data["state"]["zones"]
                    key = str(z).strip().lower()
                    hit = next((x for x in zs if key in (str(x["id"]), x["name"].lower(), chr(64 + x["id"]).lower(), f"zone {chr(64 + x['id'])}".lower())), None)
                    if not hit:
                        raise HomeAssistantError(f"no zone called {z}")
                    zones.append(hit["id"])
                try:
                    await c.client.announce(zones, msg_id, call.data.get("text"), call.data.get("chime"))
                except HostError as e:
                    raise HomeAssistantError(str(e)) from e

        async def stop(call: ServiceCall) -> None:
            for c in hass.data.get(DOMAIN, {}).values():
                try:
                    await c.client.stop_announcements()
                except HostError as e:
                    raise HomeAssistantError(str(e)) from e

        hass.services.async_register(DOMAIN, "announce", announce, schema=ANNOUNCE_SCHEMA)
        hass.services.async_register(DOMAIN, "stop_announcements", stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "announce")
            hass.services.async_remove(DOMAIN, "stop_announcements")
    return ok
