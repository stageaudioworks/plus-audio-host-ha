"""Plus Audio Host: zones as media players, scenes, announcements, engine health, the amplifiers it controls
(Plus Audio AC403 / AC401: a power switch, temperature and a problem sensor each), and live zone meters for
dashboards (meters.py, with its card in frontend/). Local API, no cloud."""
from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HostClient, HostError
from homeassistant.loader import async_get_integration

from .const import CONF_TOKEN, CONF_VERIFY_SSL, DOMAIN, METER_CARD_URL, METER_MAX_HZ
from .coordinator import HostCoordinator
from .meters import MeterHub

FRONTEND = f"{DOMAIN}_frontend"      # hass.data key: the websocket command and the card are set up once

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH, Platform.BINARY_SENSOR]

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
    coord.meters = MeterHub(hass, coord)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    await _setup_frontend(hass)
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


async def _setup_frontend(hass: HomeAssistant) -> None:
    """once: the live meters' websocket command, and the meters card (served by the integration and loaded on every
    dashboard, so it needs no dashboard resource)"""
    if hass.data.get(FRONTEND):
        return
    hass.data[FRONTEND] = True
    websocket_api.async_register_command(hass, ws_meters)
    if hass.http is not None:              # not in some test setups
        card = Path(__file__).parent / "frontend" / "plus-audio-meters-card.js"
        await hass.http.async_register_static_paths([StaticPathConfig(METER_CARD_URL, str(card), False)])
        version = (await async_get_integration(hass, DOMAIN)).version
        add_extra_js_url(hass, f"{METER_CARD_URL}?v={version}")


@websocket_api.websocket_command({
    vol.Required("type"): "plus_audio_host/meters/subscribe",
    vol.Optional("entry_id"): str,                                     # one processor; default: all of them
    vol.Optional("rate", default=10.0): vol.All(vol.Coerce(float), vol.Range(min=1, max=METER_MAX_HZ)),   # updates a second
})
@callback
def ws_meters(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """live zone levels for a dashboard card, pushed as events until the card unsubscribes (or the page closes)"""
    coords: dict = hass.data.get(DOMAIN, {})
    eid = msg.get("entry_id")
    if eid and eid not in coords:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "no such Plus Audio Host")
        return

    @callback
    def forward(frame: dict) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], frame))

    connection.send_result(msg["id"])
    unsubs = [c.meters.subscribe(forward, msg["rate"]) for c in ([coords[eid]] if eid else coords.values())]

    @callback
    def unsub_all() -> None:
        for u in unsubs:
            u()

    connection.subscriptions[msg["id"]] = unsub_all


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        coord = hass.data[DOMAIN].get(entry.entry_id)
        if coord is not None and getattr(coord, "meters", None):
            coord.meters.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "announce")
            hass.services.async_remove(DOMAIN, "stop_announcements")
    return ok
