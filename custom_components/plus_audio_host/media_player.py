"""One media player per zone: source, volume (dB mapped to 0..1 up to the zone's limit), mute, what's playing with its
artwork, play/pause/skip while it plays the music player or the radio, and a media browser for the favourite stations
and the music channels. The music player and the radio are one each per processor: skipping or changing the station
from one zone changes it for every zone playing it (as on the processor's own panels).
One more per zone group (#81): the group's level (-40..+10 dB mapped to 0..1) and mute. Groups made later appear on the
next update; a deleted group's player goes unavailable. Boxes from before groups have none."""
from __future__ import annotations

import re

from homeassistant.components.media_player import (BrowseError, BrowseMedia, MediaClass, MediaPlayerEntity,
                                                   MediaPlayerEntityFeature, MediaPlayerState, MediaType)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import HostError
from .const import DOMAIN, GROUP_MAX_DB, GROUP_MIN_DB, VOL_FLOOR_DB
from .coordinator import HostCoordinator
from .entity import HostEntity

OFF = "Off"
LOCAL = "Processor's own music"   # the music stored on the processor (its UI: "Box's own music")
F = MediaPlayerEntityFeature
BASE = F.VOLUME_SET | F.VOLUME_MUTE | F.VOLUME_STEP | F.SELECT_SOURCE
PLAYING = {"playing": MediaPlayerState.PLAYING, "backup": MediaPlayerState.PLAYING, "paused": MediaPlayerState.PAUSED,
           "stopped": MediaPlayerState.IDLE}


def split_track(text: str) -> tuple[str | None, str | None]:
    """"Artist – Title" (Jamendo), "Artist - Title" (mpd, a station's ICY title) -> (artist, title). A file on the
    processor without tags shows as its path: its name without the folder and extension, often "Artist - Title" too."""
    base = text.rsplit("/", 1)[-1]
    if base != text or re.search(r"\.(mp3|flac|ogg|oga|opus|m4a|aac|wav|aiff?|wma)$", base, re.I):
        text = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", base)
    for sep in (" – ", " - "):
        if sep in text:
            a, t = text.split(sep, 1)
            if a.strip().isdigit():                  # "06 - Title": a track number, not an artist
                return split_track(t) if t.strip() else (None, a.strip())
            if a.strip() and t.strip():
                return a.strip(), t.strip()
    return None, (text.strip() or None)


def favourites(data: dict) -> list[dict]:
    return ((data.get("radio") or {}).get("favourites")) or []


def channels(data: dict) -> list[tuple[str, str]]:
    """(id, name): the music stored on the processor, then the Jamendo channels when Jamendo is set up"""
    ch = data.get("channels")
    if ch is None:
        return []
    out = [("local", LOCAL)]
    if ch.get("configured"):
        out += [(c["id"], c["name"]) for c in ch.get("channels") or []]
    return out


def db_to_level(db: float, top: float) -> float:
    if db is None:
        return 0.0
    return max(0.0, min(1.0, (db - VOL_FLOOR_DB) / (top - VOL_FLOOR_DB)))


def level_to_db(level: float, top: float) -> float:
    return round(VOL_FLOOR_DB + max(0.0, min(1.0, level)) * (top - VOL_FLOOR_DB), 1)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: HostCoordinator = hass.data[DOMAIN][entry.entry_id]
    add(ZonePlayer(coord, z["id"]) for z in coord.data["state"]["zones"])
    known: set[str] = set()

    def new_groups() -> None:
        fresh = [g["id"] for g in coord.data["state"].get("groups") or [] if g["id"] not in known]
        known.update(fresh)
        if fresh:
            add(GroupPlayer(coord, gid) for gid in fresh)

    new_groups()
    entry.async_on_unload(coord.async_add_listener(new_groups))


class ZonePlayer(HostEntity, MediaPlayerEntity):
    """the zone's live level isn't an attribute (it changed every update and filled the recorder): the "Plus Audio
    meters" dashboard card shows it live instead (meters.py)"""
    _attr_volume_step = 0.05

    def __init__(self, coord: HostCoordinator, zone: int) -> None:
        super().__init__(coord, f"zone{zone}")
        self._zone = zone

    @property
    def _z(self) -> dict:
        return next((z for z in self.coordinator.data["state"]["zones"] if z["id"] == self._zone), {})

    @property
    def _top(self) -> float:
        top = self._z.get("max_volume_db")
        return float(top) if top is not None else 0.0

    @property
    def name(self) -> str:
        return self._z.get("name") or f"Zone {chr(64 + self._zone)}"

    @property
    def available(self) -> bool:
        return super().available and bool(self._z) and self._z.get("in_use", True) is not False   # an installer took it out of use

    @property
    def _src(self) -> str | None:
        return self._z.get("source")

    @property
    def _np(self) -> dict:
        """what the zone's source is playing: the music player's or the radio's status, else {}"""
        st = self.coordinator.data.get("status") or {}
        return (st.get(self._src) or {}) if self._src in ("player", "radio") else {}

    @property
    def state(self) -> MediaPlayerState:
        if self._src in (None, "none"):
            return MediaPlayerState.OFF
        if self._src in ("player", "radio"):
            return PLAYING.get(self._np.get("state"), MediaPlayerState.ON)
        return MediaPlayerState.ON

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        f = BASE
        allowed = self._sources()
        if ("radio" in allowed and favourites(self.coordinator.data)) or ("player" in allowed and channels(self.coordinator.data)):
            f |= F.BROWSE_MEDIA | F.PLAY_MEDIA
        if self._src == "player":
            f |= F.PLAY | F.PAUSE | F.NEXT_TRACK | F.PREVIOUS_TRACK
        elif self._src == "radio":
            f |= F.PLAY | F.PAUSE
        return f

    @property
    def volume_level(self) -> float:
        return db_to_level(self._z.get("volume_db"), self._top)

    @property
    def is_volume_muted(self) -> bool:
        return bool(self._z.get("mute"))

    def _sources(self) -> dict[str, str]:
        """source id -> name: the zone's allowed sources (all but announcements when it allows all)"""
        src = self.coordinator.data["state"].get("sources", {})
        allowed = self._z.get("allowed_sources") or [k for k in src if k != "announce"]
        return {k: src[k].get("name", k) for k in allowed if k in src}

    @property
    def source_list(self) -> list[str]:
        return [OFF, *self._sources().values()]

    @property
    def source(self) -> str | None:
        sid = self._z.get("source")
        if sid in (None, "none"):
            return OFF
        return self.coordinator.data["state"].get("sources", {}).get(sid, {}).get("name", sid)

    def _track(self) -> tuple[str | None, str | None]:
        np = self._np
        if self._src == "player":
            return split_track(np.get("title") or "")
        if self._src == "radio":
            if np.get("now"):
                return split_track(np["now"])
            return None, np.get("station") or np.get("title") or None
        return None, None

    @property
    def media_content_type(self) -> str | None:
        return MediaType.MUSIC if self._src in ("player", "radio") and self._np.get("state") not in (None, "stopped") else None

    @property
    def media_title(self) -> str | None:
        return self._track()[1]

    @property
    def media_artist(self) -> str | None:
        return self._track()[0]

    @property
    def media_channel(self) -> str | None:
        """the station, or the music player's channel"""
        if self._src == "radio":
            return self._np.get("station") or None
        if self._src == "player":
            return self._np.get("channel") or None
        return None

    @property
    def media_image_url(self) -> str | None:
        """the track's cover (Jamendo) or the station's logo; Home Assistant fetches it and serves it on"""
        return self._np.get("image") or None

    @property
    def extra_state_attributes(self) -> dict:
        z = self._z
        live = next((x for x in (self.coordinator.data.get("status") or {}).get("zones", []) if x.get("zone") == self._zone), {})
        a = {"volume_db": z.get("volume_db"), "volume_limit_db": z.get("max_volume_db"), "zone": chr(64 + self._zone),
             "playing": live.get("active")}
        if z.get("groups"):                       # in a zone group (#81): what it actually plays at
            a.update(plays_at_db=z.get("effective_db"), muted_by_group=bool(z.get("effective_mute")) and not z.get("mute"))
        return a

    async def _put(self, **fields) -> None:
        try:
            await self.coordinator.client.set_zone(self._zone, **fields)
        except HostError as e:
            raise HomeAssistantError(str(e)) from e
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._put(volume_db=level_to_db(volume, self._top))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._put(mute=mute)

    async def async_select_source(self, source: str) -> None:
        if source == OFF:
            return await self._put(source="none")
        sid = next((k for k, n in self._sources().items() if n == source), None)
        if not sid:
            raise HomeAssistantError(f"{self.name} can't play {source}")
        await self._put(source=sid)


    # ---- transport: the shared music player or radio
    async def _do(self, coro) -> None:
        try:
            await coro
        except HostError as e:
            raise HomeAssistantError(str(e)) from e
        self.coordinator.refresh_slow()
        await self.coordinator.async_request_refresh()

    def _transport(self, cmd: str):
        c = self.coordinator.client
        if self._src == "player":
            return c.player(cmd)
        if self._src == "radio" and cmd in ("play", "pause"):
            return c.radio_cmd(cmd)
        raise HomeAssistantError(f"{self.name} isn't playing the music player or the radio")

    async def async_media_play(self) -> None:
        await self._do(self._transport("play"))

    async def async_media_pause(self) -> None:
        await self._do(self._transport("pause"))

    async def async_media_next_track(self) -> None:
        await self._do(self._transport("next"))

    async def async_media_previous_track(self) -> None:
        await self._do(self._transport("prev"))

    # ---- stations and channels: "radio/<station id>", "channel/<channel id>"
    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        kind, _, item = media_id.partition("/")
        c = self.coordinator.client
        if kind == "radio" and item:
            return await self._do(c.play_station(item, zone=self._zone))     # the processor switches the zone too
        if kind == "channel" and item:
            if "player" not in self._sources():
                raise HomeAssistantError(f"{self.name} can't play the music player")
            await self._do(c.play_channel(item))
            if self._src != "player":
                await self._put(source="player")
            return
        raise HomeAssistantError(f"can't play {media_id}")

    async def async_browse_media(self, media_content_type: str | None = None, media_content_id: str | None = None) -> BrowseMedia:
        data, allowed = self.coordinator.data, self._sources()
        stations = [BrowseMedia(media_class=MediaClass.CHANNEL, media_content_id=f"radio/{f['id']}", media_content_type=MediaType.CHANNEL,
                                title=f.get("name") or f["id"], can_play=True, can_expand=False, thumbnail=f.get("logo") or None)
                    for f in favourites(data)] if "radio" in allowed else []
        music = [BrowseMedia(media_class=MediaClass.PLAYLIST, media_content_id=f"channel/{cid}", media_content_type=MediaType.PLAYLIST,
                             title=name, can_play=True, can_expand=False) for cid, name in channels(data)] if "player" in allowed else []
        folder = lambda cid, title, kids: BrowseMedia(media_class=MediaClass.DIRECTORY, media_content_id=cid, media_content_type="",
                                                       title=title, can_play=False, can_expand=True, children=kids,
                                                       children_media_class=kids[0].media_class if kids else None)
        if media_content_id == "radio":
            return folder("radio", allowed.get("radio", "Radio"), stations)
        if media_content_id == "channel":
            return folder("channel", allowed.get("player", "Music player"), music)
        if media_content_id:
            raise BrowseError(f"nothing at {media_content_id}")
        top = [folder("radio", allowed.get("radio", "Radio"), [])] if stations else []
        top += [folder("channel", allowed.get("player", "Music player"), [])] if music else []
        for t in top:
            t.children = None
        return folder("", self.name, top)


class GroupPlayer(HostEntity, MediaPlayerEntity):
    """a zone group's master: turns its zones up or down together; their own volumes don't move"""
    _attr_supported_features = MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_MUTE | MediaPlayerEntityFeature.VOLUME_STEP
    _attr_volume_step = 0.04                  # 2 dB

    def __init__(self, coord: HostCoordinator, gid: str) -> None:
        super().__init__(coord, f"group_{gid}")
        self._gid = gid

    @property
    def _g(self) -> dict:
        return next((g for g in self.coordinator.data["state"].get("groups") or [] if g["id"] == self._gid), {})

    @property
    def name(self) -> str:
        return f"{self._g.get('name') or 'Zone group'} (group)"

    @property
    def available(self) -> bool:
        return super().available and bool(self._g)

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float:
        return max(0.0, min(1.0, (float(self._g.get("offset_db", 0)) - GROUP_MIN_DB) / (GROUP_MAX_DB - GROUP_MIN_DB)))

    @property
    def is_volume_muted(self) -> bool:
        return bool(self._g.get("mute"))

    @property
    def extra_state_attributes(self) -> dict:
        names = {z["id"]: z["name"] for z in self.coordinator.data["state"].get("zones", [])}
        return {"group_db": self._g.get("offset_db"), "zones": [names[i] for i in self._g.get("zones", []) if i in names]}

    async def _put(self, **fields) -> None:
        try:
            await self.coordinator.client.set_group(self._gid, **fields)
        except HostError as e:
            raise HomeAssistantError(str(e)) from e
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._put(offset_db=round(GROUP_MIN_DB + max(0.0, min(1.0, volume)) * (GROUP_MAX_DB - GROUP_MIN_DB), 1))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._put(mute=mute)
