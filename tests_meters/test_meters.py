import asyncio
from types import SimpleNamespace

import pytest
from aiohttp import WSMsgType, web

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.setup import async_setup_component

import custom_components.plus_audio_host as pah
from custom_components.plus_audio_host import _setup_frontend
from custom_components.plus_audio_host.api import HostClient
from custom_components.plus_audio_host.const import DOMAIN
from custom_components.plus_audio_host.meters import MeterHub

TOKEN = "bmp_test"
STATE = {"device_name": "Test Host", "zones": [
    {"id": 1, "name": "Lobby", "source": "Radio", "mute": False},
    {"id": 2, "name": "", "in_use": False},
    {"id": 3, "name": "Bar", "source": "Music", "mute": True},
]}
ZONES = [{"zone": 1, "peak_db": [-12.5, -14.0], "rms_db": [-20, -21], "active": True},
         {"zone": 3, "peak_db": -30, "active": True}]


async def _box(aiohttp_server, push: bool, meters: bool):
    """a fake processor: /api/status always; /api/meters and /api/meters/ws when asked for"""
    hits = {"status": 0, "meters": 0, "ws": 0}

    def auth(req):
        if req.headers.get("X-BMP-Token") != TOKEN:
            raise web.HTTPUnauthorized()

    async def status(req):
        auth(req); hits["status"] += 1
        return web.json_response({"zones": [{"zone": 1, "peak_db": [-40, -41]}]})

    async def meters_(req):
        auth(req); hits["meters"] += 1
        return web.json_response({"zones": ZONES})

    async def ws(req):
        auth(req); hits["ws"] += 1
        s = web.WebSocketResponse()
        await s.prepare(req)
        for _ in range(200):
            if s.closed:
                break
            await s.send_json({"zones": ZONES})
            await asyncio.sleep(0.01)
        return s

    app = web.Application()
    app.router.add_get("/api/status", status)
    if meters:
        app.router.add_get("/api/meters", meters_)
    if push:
        app.router.add_get("/api/meters/ws", ws)
    server = await aiohttp_server(app)
    return f"http://127.0.0.1:{server.port}", hits


def _coord(hass, url, token=TOKEN, entry_id="e1"):
    client = HostClient(async_get_clientsession(hass), url, token)
    c = SimpleNamespace(client=client, data={"state": STATE}, config_entry=SimpleNamespace(entry_id=entry_id))
    c.meters = MeterHub(hass, c)
    return c


async def _collect(hub, n, rate=20.0, timeout=5.0):
    got, done = [], asyncio.Event()

    def cb(f):
        got.append(f)
        if len(got) >= n:
            done.set()
    unsub = hub.subscribe(cb, rate)
    await asyncio.wait_for(done.wait(), timeout)
    unsub()
    await asyncio.sleep(0.05)
    return got


@pytest.fixture
def js_urls(monkeypatch):
    """the frontend component needs the hass_frontend package, not installed here: record the card's URL instead"""
    urls = []
    monkeypatch.setattr(pah, "add_extra_js_url", lambda hass, url: urls.append(url))
    return urls


@pytest.mark.parametrize(("push", "meters", "mode"), [(True, True, "push"), (False, True, "meters"), (False, False, "status")])
async def test_sources(hass: HomeAssistant, aiohttp_server, push, meters, mode):
    url, hits = await _box(aiohttp_server, push, meters)
    c = _coord(hass, url)
    frames = await _collect(c.meters, 4)
    assert frames[0]["mode"] == "starting" and frames[0]["zones"][0]["peak_db"] == []      # layout first
    f = frames[-1]
    assert f["mode"] == mode and f["device"] == "Test Host" and f["entry_id"] == "e1"
    assert [z["letter"] for z in f["zones"]] == ["A", "C"]                                 # zone B is out of use
    assert f["zones"][1]["name"] == "Bar" and f["zones"][1]["mute"] is True
    if mode == "status":
        assert f["zones"][0]["peak_db"] == [-40.0, -41.0] and f["zones"][1]["peak_db"] == []
    else:
        assert f["zones"][0]["peak_db"] == [-12.5, -14.0] and f["zones"][0]["rms_db"] == [-20.0, -21.0]
        assert f["zones"][1]["peak_db"] == [-30.0]
    assert c.meters._task.done()                                                           # stops with no card open


async def test_rate_and_stop(hass: HomeAssistant, aiohttp_server):
    url, hits = await _box(aiohttp_server, False, True)
    c = _coord(hass, url)
    got = []
    unsub = c.meters.subscribe(got.append, 5)
    await asyncio.sleep(1.1)
    unsub()
    assert 4 <= hits["meters"] <= 8, hits                                                  # about 5 a second
    before = hits["meters"]
    await asyncio.sleep(0.5)
    assert hits["meters"] == before                                                        # nothing while nobody looks


async def test_bad_token(hass: HomeAssistant, aiohttp_server):
    url, _ = await _box(aiohttp_server, True, True)
    c = _coord(hass, url, token="wrong")
    frames = await _collect(c.meters, 2)
    assert frames[1]["mode"] == "error" and "refused" in frames[1]["error"]


async def test_websocket_command(hass: HomeAssistant, hass_ws_client, aiohttp_server, js_urls):
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "websocket_api", {})      # (the frontend itself needs hass_frontend)
    url, _ = await _box(aiohttp_server, True, True)
    hass.data.setdefault(DOMAIN, {})["e1"] = _coord(hass, url)
    await _setup_frontend(hass)
    ws = await hass_ws_client(hass)

    await ws.send_json({"id": 1, "type": "plus_audio_host/meters/subscribe", "entry_id": "nope"})
    r = await ws.receive_json()
    assert not r["success"] and r["error"]["code"] == "not_found"

    await ws.send_json({"id": 2, "type": "plus_audio_host/meters/subscribe", "rate": 20})
    assert (await ws.receive_json())["success"]
    modes = []
    for _ in range(4):
        ev = await ws.receive_json()
        assert ev["type"] == "event" and ev["id"] == 2
        modes.append(ev["event"]["mode"])
    assert modes[0] == "starting" and modes[-1] == "push"

    await ws.send_json({"id": 3, "type": "unsubscribe_events", "subscription": 2})
    while (m := await ws.receive_json())["id"] != 3:
        pass
    assert m["success"]
    await asyncio.sleep(0.1)
    assert hass.data[DOMAIN]["e1"].meters._task.done()


async def test_card_served(hass: HomeAssistant, hass_client, js_urls):
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "websocket_api", {})
    await _setup_frontend(hass)
    await _setup_frontend(hass)                     # a second processor: set up once only
    r = await (await hass_client()).get("/plus_audio_host/plus-audio-meters-card.js")
    assert r.status == 200 and "plus-audio-meters-card" in await r.text()
    assert js_urls == ["/plus_audio_host/plus-audio-meters-card.js?v=0.3.0"]           # loaded on every dashboard

