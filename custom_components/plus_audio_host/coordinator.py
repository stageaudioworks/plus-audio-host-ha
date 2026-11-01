from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HostAuthError, HostClient, HostError
from .const import DOMAIN, SCAN_SECONDS

_LOG = logging.getLogger(__name__)


class HostCoordinator(DataUpdateCoordinator[dict]):
    """state + status every 5 s; scenes and messages every minute (they change rarely)"""

    def __init__(self, hass: HomeAssistant, client: HostClient) -> None:
        super().__init__(hass, _LOG, name=DOMAIN, update_interval=timedelta(seconds=SCAN_SECONDS))
        self.client = client
        self._slow: dict = {}
        self._slow_t = 0.0

    async def _async_update_data(self) -> dict:
        try:
            state = await self.client.state()
            status = await self.client.status()
            if time.monotonic() - self._slow_t > 60 or not self._slow:
                self._slow = {"scenes": await self.client.scenes(), "messages": await self.client.messages()}
                self._slow_t = time.monotonic()
        except HostAuthError as e:
            raise ConfigEntryAuthFailed(str(e)) from e
        except HostError as e:
            raise UpdateFailed(str(e)) from e
        return {"state": state, "status": status, **self._slow}

    def refresh_slow(self) -> None:
        self._slow_t = 0.0
