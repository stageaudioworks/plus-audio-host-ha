"""Scenes as a select: shows the last scene that ran, choosing one runs it. And, for the whole processor, the radio
station (its favourites) and the music player's channel: choosing one changes it for every zone playing it."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import HostError
from .const import DOMAIN
from .coordinator import HostCoordinator
from .entity import HostEntity
from .media_player import channels, favourites


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: HostCoordinator = hass.data[DOMAIN][entry.entry_id]
    ents: list[SelectEntity] = [SceneSelect(coord)]
    if coord.data.get("radio") is not None:          # processors from before the radio have neither
        ents.append(StationSelect(coord))
    if coord.data.get("channels") is not None:
        ents.append(ChannelSelect(coord))
    add(ents)


class SceneSelect(HostEntity, SelectEntity):
    _attr_translation_key = "scene"
    _attr_icon = "mdi:palette-outline"

    def __init__(self, coord: HostCoordinator) -> None:
        super().__init__(coord, "scene")

    @property
    def _scenes(self) -> list[dict]:
        return (self.coordinator.data.get("scenes") or {}).get("scenes", [])

    @property
    def options(self) -> list[str]:
        return [s["name"] for s in self._scenes]

    @property
    def current_option(self) -> str | None:
        last = ((self.coordinator.data.get("scenes") or {}).get("day") or {}).get("last") or {}
        return next((s["name"] for s in self._scenes if s["id"] == last.get("id")), None)

    async def async_select_option(self, option: str) -> None:
        s = next((x for x in self._scenes if x["name"] == option), None)
        if not s:
            raise HomeAssistantError(f"no scene called {option}")
        try:
            await self.coordinator.client.run_scene(s["id"])
        except HostError as e:
            raise HomeAssistantError(str(e)) from e
        self.coordinator.refresh_slow()
        await self.coordinator.async_request_refresh()


class StationSelect(HostEntity, SelectEntity):
    """the radio's station, from the processor's favourites (staff can play those only)"""
    _attr_translation_key = "radio_station"
    _attr_icon = "mdi:radio"

    def __init__(self, coord: HostCoordinator) -> None:
        super().__init__(coord, "radio_station")

    @property
    def available(self) -> bool:
        return super().available and bool(favourites(self.coordinator.data))

    @property
    def options(self) -> list[str]:
        return [f.get("name") or f["id"] for f in favourites(self.coordinator.data)]

    @property
    def current_option(self) -> str | None:
        r = (self.coordinator.data.get("status") or {}).get("radio") or {}
        if r.get("state", "stopped") == "stopped":
            return None
        return r.get("station") if r.get("station") in self.options else None

    async def async_select_option(self, option: str) -> None:
        f = next((x for x in favourites(self.coordinator.data) if (x.get("name") or x["id"]) == option), None)
        if not f:
            raise HomeAssistantError(f"{option} isn't one of the processor's favourite stations")
        try:
            await self.coordinator.client.play_station(f["id"])
        except HostError as e:
            raise HomeAssistantError(str(e)) from e
        self.coordinator.refresh_slow()
        await self.coordinator.async_request_refresh()


class ChannelSelect(HostEntity, SelectEntity):
    """the music player's channel: the processor's own music, or a Jamendo channel when Jamendo is set up"""
    _attr_translation_key = "music_channel"
    _attr_icon = "mdi:playlist-music"

    def __init__(self, coord: HostCoordinator) -> None:
        super().__init__(coord, "music_channel")

    @property
    def options(self) -> list[str]:
        return [name for _, name in channels(self.coordinator.data)]

    @property
    def current_option(self) -> str | None:
        p = (self.coordinator.data.get("status") or {}).get("player") or {}
        if p.get("channel"):
            return p["channel"] if p["channel"] in self.options else None
        if p.get("state", "stopped") != "stopped" and not (self.coordinator.data.get("channels") or {}).get("channel"):
            return self.options[0] if self.options else None      # playing, no channel: the processor's own music
        return None

    async def async_select_option(self, option: str) -> None:
        cid = next((i for i, n in channels(self.coordinator.data) if n == option), None)
        if not cid:
            raise HomeAssistantError(f"no music channel called {option}")
        try:
            await self.coordinator.client.play_channel(cid)
        except HostError as e:
            raise HomeAssistantError(str(e)) from e
        self.coordinator.refresh_slow()
        await self.coordinator.async_request_refresh()
