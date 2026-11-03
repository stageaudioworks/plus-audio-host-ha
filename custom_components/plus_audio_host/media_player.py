"""One media player per zone: source, volume (dB mapped to 0..1 up to the zone's limit), mute, what's playing.
One more per zone group (#81): the group's level (-40..+10 dB mapped to 0..1) and mute. Groups made later appear on the
next update; a deleted group's player goes unavailable. Boxes from before groups have none."""
from __future__ import annotations

from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerEntityFeature, MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import HostError
from .const import DOMAIN, GROUP_MAX_DB, GROUP_MIN_DB, VOL_FLOOR_DB
from .coordinator import HostCoordinator
from .entity import HostEntity

OFF = "Off"


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
    _attr_supported_features = (MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_MUTE
                                | MediaPlayerEntityFeature.VOLUME_STEP | MediaPlayerEntityFeature.SELECT_SOURCE)
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
        return super().available and bool(self._z)

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.OFF if self._z.get("source") in (None, "none") else MediaPlayerState.ON

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

    @property
    def media_title(self) -> str | None:
        st = self.coordinator.data.get("status") or {}
        sid = self._z.get("source")
        if sid == "player":
            return (st.get("player") or {}).get("title") or None
        if sid == "radio":
            return (st.get("radio") or {}).get("title") or None
        return None

    @property
    def extra_state_attributes(self) -> dict:
        z = self._z
        live = next((x for x in (self.coordinator.data.get("status") or {}).get("zones", []) if x.get("zone") == self._zone), {})
        a = {"volume_db": z.get("volume_db"), "volume_limit_db": z.get("max_volume_db"), "zone": chr(64 + self._zone),
             "level_db": max(live.get("peak_db") or [-120]), "playing": live.get("active")}
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
