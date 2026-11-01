from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HostCoordinator


class HostEntity(CoordinatorEntity[HostCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coord: HostCoordinator, key: str) -> None:
        super().__init__(coord)
        self._serial = coord.config_entry.unique_id or coord.config_entry.entry_id
        self._attr_unique_id = f"{self._serial}_{key}"
        dev = (coord.data.get("status") or {}).get("device") or {}
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._serial)}, manufacturer="Plus Audio",
                                            model=f"Plus Audio {dev.get('model') or 'Host'}", sw_version=dev.get("version"),
                                            serial_number=dev.get("serial"), name=coord.data["state"].get("device_name") or "Plus Audio Host",
                                            configuration_url=coord.client.url)
