"""Scenes as a select: shows the last scene that ran, choosing one runs it."""
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    add([SceneSelect(hass.data[DOMAIN][entry.entry_id])])


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
