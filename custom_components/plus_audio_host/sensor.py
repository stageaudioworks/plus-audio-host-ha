"""Health: audio dropouts (engine xruns), the network clock (PTP), network inputs with problems."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HostCoordinator
from .entity import HostEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    c = hass.data[DOMAIN][entry.entry_id]
    add([Dropouts(c), Clock(c), InputProblems(c)])


class _Diag(HostEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def _st(self) -> dict:
        return self.coordinator.data.get("status") or {}


class Dropouts(_Diag):
    _attr_translation_key = "dropouts"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:waveform"

    def __init__(self, c: HostCoordinator) -> None:
        super().__init__(c, "xruns")

    @property
    def native_value(self):
        return (self._st.get("engine") or {}).get("xruns")

    @property
    def extra_state_attributes(self) -> dict:
        e = self._st.get("engine") or {}
        return {"engine_running": e.get("up"), "processing_max_us": e.get("proc_max_us")}


class Clock(_Diag):
    _attr_translation_key = "clock"
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, c: HostCoordinator) -> None:
        super().__init__(c, "ptp")

    @property
    def native_value(self):
        return (self._st.get("ptp") or {}).get("status")


class InputProblems(_Diag):
    _attr_translation_key = "input_problems"
    _attr_icon = "mdi:lan-disconnect"

    def __init__(self, c: HostCoordinator) -> None:
        super().__init__(c, "net_in_problems")

    @property
    def native_value(self):
        return (self._st.get("net_in") or {}).get("problems")

    @property
    def extra_state_attributes(self) -> dict:
        return {"network_inputs": (self._st.get("net_in") or {}).get("flows")}
