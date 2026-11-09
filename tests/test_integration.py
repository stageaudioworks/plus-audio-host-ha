import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from custom_components.plus_audio_host.const import CONF_TOKEN, DOMAIN


async def _setup(hass: HomeAssistant, url: str, token: str):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_URL: url, CONF_TOKEN: token})
    await hass.async_block_till_done()
    return r


async def test_bad_token_refused(hass: HomeAssistant, box):
    url, _, _ = box
    r = await _setup(hass, url, "bmp_not_a_real_token")
    assert r["type"] == FlowResultType.FORM and r["errors"] == {"base": "invalid_auth"}


async def test_unreachable(hass: HomeAssistant):
    r = await _setup(hass, "http://127.0.0.1:9", "bmp_x")
    assert r["errors"] == {"base": "cannot_connect"}


async def test_zones_scenes_announce(hass: HomeAssistant, box):
    url, token, call = box
    state = call("GET", "/api/state")[1]
    r = await _setup(hass, url, token)
    assert r["type"] == FlowResultType.CREATE_ENTRY, r
    assert r["title"] == state["device_name"]
    assert r["result"].unique_id == "HA-TEST-1"

    zones = state["zones"]
    players = hass.states.async_all("media_player")
    assert len(players) == len(zones)
    z1 = zones[0]
    ent = next(p for p in players if p.attributes["friendly_name"].endswith(z1["name"]))
    eid = ent.entity_id
    assert ent.attributes["volume_db"] == z1["volume_db"]
    assert "Music player" in ent.attributes["source_list"] and "Off" in ent.attributes["source_list"]
    assert "Announcements" not in ent.attributes["source_list"]

    # volume: 0..1 is -60 dB .. the zone's limit (0 dB here)
    await hass.services.async_call("media_player", "volume_set", {"entity_id": eid, "volume_level": 0.5}, blocking=True)
    assert call("GET", "/api/state")[1]["zones"][0]["volume_db"] == pytest.approx(-30.0, abs=0.2)
    await hass.services.async_call("media_player", "volume_mute", {"entity_id": eid, "is_volume_muted": True}, blocking=True)
    assert call("GET", "/api/state")[1]["zones"][0]["mute"] is True
    await hass.services.async_call("media_player", "select_source", {"entity_id": eid, "source": "Music player"}, blocking=True)
    assert call("GET", "/api/state")[1]["zones"][0]["source"] == "player"
    await hass.services.async_call("media_player", "select_source", {"entity_id": eid, "source": "Off"}, blocking=True)
    await hass.async_block_till_done()
    assert call("GET", "/api/state")[1]["zones"][0]["source"] == "none"
    assert hass.states.get(eid).state == "off"

    # with a lower limit, 100 % is the limit: Home Assistant can't make it louder than staff can
    call("PUT", "/api/zones/1", {"max_volume_db": -20})
    await hass.data[DOMAIN][r["result"].entry_id].async_refresh()
    await hass.services.async_call("media_player", "volume_set", {"entity_id": eid, "volume_level": 1.0}, blocking=True)
    assert call("GET", "/api/state")[1]["zones"][0]["volume_db"] == pytest.approx(-20.0, abs=0.2)

    # zone groups (#81): a player per group, made on the next update; its level and mute go to the box
    call("PUT", "/api/zones/1", {"max_volume_db": 0, "volume_db": -20, "mute": False})
    g = call("POST", "/api/groups", {"name": "Front", "zones": [1, 2]})[1]["group"]
    await hass.data[DOMAIN][r["result"].entry_id].async_refresh()
    await hass.async_block_till_done()
    gp = next(p for p in hass.states.async_all("media_player") if p.attributes["friendly_name"].endswith("Front (group)"))
    assert gp.attributes["zones"] == [zones[0]["name"], zones[1]["name"]] and gp.attributes["volume_level"] == pytest.approx(0.8)
    await hass.services.async_call("media_player", "volume_set", {"entity_id": gp.entity_id, "volume_level": 0.68}, blocking=True)
    st = call("GET", "/api/state")[1]
    assert st["groups"][0]["offset_db"] == pytest.approx(-6.0) and st["zones"][0]["volume_db"] == -20
    assert hass.states.get(eid).attributes["plays_at_db"] == pytest.approx(-26.0)
    await hass.services.async_call("media_player", "volume_mute", {"entity_id": gp.entity_id, "is_volume_muted": True}, blocking=True)
    assert call("GET", "/api/state")[1]["groups"][0]["mute"] is True
    await hass.data[DOMAIN][r["result"].entry_id].async_refresh()      # (the refresh after a change is debounced)
    await hass.async_block_till_done()
    assert hass.states.get(eid).attributes["muted_by_group"] is True and call("GET", "/api/state")[1]["zones"][0]["mute"] is False
    call("DELETE", f"/api/groups/{g['id']}", {})
    await hass.data[DOMAIN][r["result"].entry_id].async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(gp.entity_id).state == "unavailable"

    # scenes
    sel = next(s for s in hass.states.async_all("select") if s.attributes["friendly_name"].endswith("Scene"))
    assert sel.attributes["options"] == ["Lunch", "Dinner"]
    await hass.services.async_call("select", "select_option", {"entity_id": sel.entity_id, "option": "Dinner"}, blocking=True)
    sc = call("GET", "/api/scenes")[1]
    assert next(s["name"] for s in sc["scenes"] if s["id"] == sc["day"]["last"]["id"]) == "Dinner"

    # announcements: text to zones by name and letter; unknown zones and messages are refused
    await hass.services.async_call(DOMAIN, "announce", {"text": "Kitchen closes soon", "zones": [z1["name"], "B"]}, blocking=True)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "announce", {"text": "x", "zones": ["Nowhere"]}, blocking=True)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "announce", {"message": "No such message"}, blocking=True)
    audit = call("GET", "/api/audit")[1]
    assert any("Home Assistant" in str(a) for a in (audit.get("entries") or audit.get("audit") or [])), audit

    # health sensors
    names = {s.attributes.get("friendly_name", "") for s in hass.states.async_all("sensor")}
    assert any(n.endswith("Audio dropouts") for n in names) and any(n.endswith("Network clock") for n in names)


async def test_music_and_radio(hass: HomeAssistant, box):
    """artwork and track details, play/pause/skip on the shared music player, stations and channels from the media
    browser and the processor-wide selects; staff are kept to the favourite stations"""
    import asyncio
    import subprocess
    import tunein_mock
    url, token, call = box
    for sid in ("s1001", "s1002"):                # the installer's favourites (names and logos come from TuneIn)
        assert call("POST", "/api/radio/favourites", {"id": sid})[0] == 200
    favs = {f["id"]: f for f in call("GET", "/api/radio")[1]["favourites"]}
    r = await _setup(hass, url, token)
    assert r["type"] == FlowResultType.CREATE_ENTRY, r
    coord = hass.data[DOMAIN][r["result"].entry_id]

    async def fresh():                            # the box's now-playing status is cached for 3 s
        await asyncio.sleep(3.1)
        coord.refresh_slow()
        await coord.async_refresh()
        await hass.async_block_till_done()

    zones = call("GET", "/api/state")[1]["zones"]
    pl = {p.attributes["friendly_name"]: p.entity_id for p in hass.states.async_all("media_player")}
    z1 = next(e for n, e in pl.items() if n.endswith(zones[0]["name"]))
    z2 = next(e for n, e in pl.items() if n.endswith(zones[1]["name"]))
    sel = {s.attributes["friendly_name"]: s for s in hass.states.async_all("select")}
    station = next(s for n, s in sel.items() if n.endswith("Radio station"))
    channel = next(s for n, s in sel.items() if n.endswith("Music player channel"))
    assert station.attributes["options"] == [favs["s1001"]["name"], favs["s1002"]["name"]]
    assert channel.attributes["options"] == ["Processor's own music"]          # Jamendo isn't set up on this box

    # the media browser: the favourite stations (with logos) and the channels
    ent = hass.data["media_player"].get_entity(z1)
    top = await ent.async_browse_media()
    assert [c.media_content_id for c in top.children] == ["radio", "channel"]
    radio = await ent.async_browse_media(None, "radio")
    assert [(c.media_content_id, c.thumbnail) for c in radio.children] == [(f"radio/{i}", favs[i]["logo"]) for i in ("s1001", "s1002")]

    # play a station in zone B from the browser: the zone switches to the radio; its logo becomes the artwork
    await hass.services.async_call("media_player", "play_media", {"entity_id": z2, "media_content_id": "radio/s1002",
                                                                  "media_content_type": "channel"}, blocking=True)
    assert call("GET", "/api/state")[1]["zones"][1]["source"] == "radio"
    assert call("GET", "/api/radio")[1]["station"]["id"] == "s1002"
    await fresh()
    s2 = hass.states.get(z2)
    assert s2.state == "playing" and s2.attributes["media_channel"] == favs["s1002"]["name"], s2.attributes
    assert s2.attributes.get("entity_picture") and coord.data["status"]["radio"]["image"] == favs["s1002"]["logo"]
    assert hass.states.get(station.entity_id).state == favs["s1002"]["name"]
    # pause and carry on (the radio is the processor's: every zone on it)
    await hass.services.async_call("media_player", "media_pause", {"entity_id": z2}, blocking=True)
    assert tunein_mock.radio()["state"] == "paused"
    await hass.services.async_call("media_player", "media_play", {"entity_id": z2}, blocking=True)
    assert tunein_mock.radio()["state"] == "playing"
    # the station select changes it for the whole processor
    await hass.services.async_call("select", "select_option", {"entity_id": station.entity_id, "option": favs["s1001"]["name"]}, blocking=True)
    assert call("GET", "/api/radio")[1]["station"]["id"] == "s1001"
    # staff (and so Home Assistant) can play the favourites only
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("media_player", "play_media", {"entity_id": z2, "media_content_id": "radio/s1004",
                                                                      "media_content_type": "channel"}, blocking=True)

    # the music player: zone A to the processor's own music from the browser, then skip and pause
    await hass.services.async_call("media_player", "play_media", {"entity_id": z1, "media_content_id": "channel/local",
                                                                  "media_content_type": "playlist"}, blocking=True)
    assert call("GET", "/api/state")[1]["zones"][0]["source"] == "player" and tunein_mock.mpd()["state"] == "playing"
    subprocess.run(["mpc", "add", "Music/Abdullah Ibrahim - Mannenberg.flac", "Music/untagged-track.mp3"], check=True)
    await fresh()
    s1 = hass.states.get(z1)
    assert s1.state == "playing" and s1.attributes["supported_features"] & 32, s1.attributes      # NEXT_TRACK
    assert hass.states.get(channel.entity_id).state == "Processor's own music"
    await hass.services.async_call("media_player", "media_next_track", {"entity_id": z1}, blocking=True)
    assert tunein_mock.mpd()["cur"] == 1
    await fresh()
    s1 = hass.states.get(z1)
    assert (s1.attributes.get("media_artist"), s1.attributes.get("media_title")) == ("Abdullah Ibrahim", "Mannenberg"), s1.attributes
    await hass.services.async_call("media_player", "media_next_track", {"entity_id": z1}, blocking=True)
    await fresh()
    assert hass.states.get(z1).attributes.get("media_title") == "untagged-track"     # no tags: the file's name
    await hass.services.async_call("media_player", "media_previous_track", {"entity_id": z1}, blocking=True)
    assert tunein_mock.mpd()["cur"] == 1
    await hass.services.async_call("media_player", "media_pause", {"entity_id": z1}, blocking=True)
    assert tunein_mock.mpd()["state"] == "paused"
    await fresh()
    assert hass.states.get(z1).state == "paused"

    # a zone that is off has no transport, and says so if asked
    call("PUT", "/api/zones/3", {"source": "none"})
    await fresh()
    z3 = next(e for n, e in pl.items() if n.endswith(zones[2]["name"]))
    assert not hass.states.get(z3).attributes["supported_features"] & 32
    with pytest.raises(HomeAssistantError):
        await hass.data["media_player"].get_entity(z3).async_media_next_track()
    call("PUT", "/api/zones/1", {"source": "none"})
    call("PUT", "/api/zones/2", {"source": "none"})


async def test_older_processor_without_radio(hass: HomeAssistant, box, monkeypatch):
    """a processor from before the radio and the music channels (those calls answer 404): everything else works,
    there are no station or channel selects and no media browser"""
    from custom_components.plus_audio_host.api import HostClient, HostError

    async def missing(self):
        raise HostError("HTTP 404")
    monkeypatch.setattr(HostClient, "radio", missing)
    monkeypatch.setattr(HostClient, "channels", missing)
    url, token, _ = box
    r = await _setup(hass, url, token)
    assert r["type"] == FlowResultType.CREATE_ENTRY, r
    names = [s.attributes["friendly_name"] for s in hass.states.async_all("select")]
    assert any(n.endswith("Scene") for n in names) and not any(n.endswith(("Radio station", "Music player channel")) for n in names)
    for p in hass.states.async_all("media_player"):
        assert not p.attributes["supported_features"] & 131072      # BROWSE_MEDIA


async def test_amplifiers(hass: HomeAssistant, box):
    """an amplifier on the box (the PN43R simulator) appears as a power switch, a temperature and a problem sensor;
    the switch puts it into standby and back"""
    import asyncio
    import os
    import subprocess
    import sys
    import harness
    sim_port = harness.free_port()                # in its own process: the test plugin doesn't allow leftover threads
    sim = subprocess.Popen([sys.executable, os.path.join(harness.CTL_DIR, "test", "amp_sim.py"), "--port", str(sim_port), "--host", "127.0.0.1"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await asyncio.sleep(0.5)
    url, token, call = box
    st, j = call("POST", "/api/amps", {"name": "Bar amp", "host": "127.0.0.1", "port": sim_port, "outputs": [{"zone": 1}, {"zone": 1}]})
    assert st == 200, j
    aid = j["amp"]["id"]
    try:
        for _ in range(60):                       # the box connects and reads it
            a = call("GET", "/api/amps")[1]["amps"][0]
            if a["status"]["online"] and a["status"]["temp_c"] is not None and a["status"]["standby"] is not None:
                break
            await asyncio.sleep(0.25)
        r = await _setup(hass, url, token)
        assert r["type"] == FlowResultType.CREATE_ENTRY, r
        sw = next(s for s in hass.states.async_all("switch") if s.attributes["friendly_name"].endswith("Bar amp power"))
        assert sw.state == "on"
        t = next(s for s in hass.states.async_all("sensor") if s.attributes["friendly_name"].endswith("Bar amp temperature"))
        assert float(t.state) == pytest.approx(41.5)
        pb = next(s for s in hass.states.async_all("binary_sensor") if s.attributes["friendly_name"].endswith("Bar amp problem"))
        assert pb.state == "off"
        async def standby_is(want):
            for _ in range(40):
                if call("GET", "/api/amps")[1]["amps"][0]["status"]["standby"] is want:
                    return True
                await asyncio.sleep(0.2)
            return False
        for _ in range(150):                      # an announcement from the test before holds standby until it ends (by design)
            ann = call("GET", "/api/messages")[1]["status"]
            if not ann["now"] and not ann["queue"]:
                break
            await asyncio.sleep(0.2)
        await hass.services.async_call("switch", "turn_off", {"entity_id": sw.entity_id}, blocking=True)
        assert await standby_is(True), call("GET", "/api/amps")[1]["log"]   # the box read it back from the amplifier
        await hass.services.async_call("switch", "turn_on", {"entity_id": sw.entity_id}, blocking=True)
        assert await standby_is(False)
    finally:
        call("DELETE", f"/api/amps/{aid}", {})
        sim.terminate()


async def test_reconfigure(hass: HomeAssistant, box):
    """the processor got a new address (a DHCP lease changed): Reconfigure points the entry at it; a wrong token is refused"""
    url, token, _ = box
    r = await _setup(hass, url, token)
    assert r["type"] == FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_URL: "http://127.0.0.1:9"})   # the old address
    start = lambda: hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id})
    r = await start()
    assert r["type"] == FlowResultType.FORM and r["step_id"] == "reconfigure"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_URL: url, CONF_TOKEN: "bmp_wrong"})
    assert r["errors"] == {"base": "invalid_auth"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_URL: url, CONF_TOKEN: token})
    await hass.async_block_till_done()
    assert r["type"] == FlowResultType.ABORT and r["reason"] == "reconfigure_successful"
    assert entry.data[CONF_URL] == url
