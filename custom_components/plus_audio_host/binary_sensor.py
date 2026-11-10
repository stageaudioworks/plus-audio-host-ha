"""One problem sensor per amplifier: on while it isn't answering, is in protection, is hot, or an output in use has a
short, no speaker, or a measured load far from its saved normal. The texts are in the `problems` attribute.
`loads_ohm` holds measured loads only (null where the amplifier doesn't measure, or hasn't yet: some firmware only reports
its load setting); `load_state` says which, per output: measured, setting, not_measured, open (processor software from
10 Nov 2026; older software has no `load_state`, and its `loads_ohm` may be the amplifier's setting)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .amp import AmpEntity, follow_amps
from .const import DOMAIN
from .coordinator import HostCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    follow_amps(hass.data[DOMAIN][entry.entry_id], entry, add, AmpProblem)


class AmpProblem(AmpEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coord: HostCoordinator, aid: str) -> None:
        super().__init__(coord, aid, "problem")

    @property
    def name(self) -> str:
        return f"{self._a.get('name') or 'Amplifier'} problem"

    @property
    def is_on(self) -> bool:
        return bool(self._a.get("problems"))

    @property
    def extra_state_attributes(self) -> dict:
        s = self._s
        return {"problems": self._a.get("problems") or [], "online": s.get("online"), "protection": s.get("protect"),
                "loads_ohm": s.get("loads_ohm"), "load_state": s.get("load_state"), "faults": s.get("faults")}
