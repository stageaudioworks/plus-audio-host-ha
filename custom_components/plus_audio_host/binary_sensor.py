"""One problem sensor per amplifier: on while it isn't answering, is in protection, is hot, or an output in use has a
short, no speaker, or a load far from its saved normal. The texts are in the `problems` attribute."""
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
                "loads_ohm": s.get("loads_ohm"), "faults": s.get("faults")}
