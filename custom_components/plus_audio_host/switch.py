"""One switch per amplifier: on = running, off = standby. Unavailable while the amplifier isn't answering or has no
standby control. The box itself refuses standby during the fire alarm, and announcements wake an amplifier by themselves."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .amp import AmpEntity, follow_amps
from .api import HostError
from .const import DOMAIN
from .coordinator import HostCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    follow_amps(hass.data[DOMAIN][entry.entry_id], entry, add, AmpPower)


class AmpPower(AmpEntity, SwitchEntity):
    _attr_icon = "mdi:amplifier"

    def __init__(self, coord: HostCoordinator, aid: str) -> None:
        super().__init__(coord, aid, "power")

    @property
    def name(self) -> str:
        return f"{self._a.get('name') or 'Amplifier'} power"

    @property
    def available(self) -> bool:
        s = self._s
        return super().available and bool(s.get("online")) and "standby" not in (s.get("unsupported") or []) and s.get("standby") is not None

    @property
    def is_on(self) -> bool:
        return self._s.get("standby") is False

    @property
    def extra_state_attributes(self) -> dict:
        return {"model": self._a.get("model"), "woken_for_announcement": self._a.get("woken_for_announcement"),
                "zones": sorted({o["zone_name"] for o in self._a.get("outputs", []) if o.get("zone_name")})}

    async def _power(self, standby: bool) -> None:
        try:
            await self.coordinator.client.amp_power(self._aid, standby)
        except HostError as e:
            raise HomeAssistantError(str(e)) from e
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._power(False)

    async def async_turn_off(self, **kwargs) -> None:
        await self._power(True)
