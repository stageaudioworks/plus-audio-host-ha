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
    """state + status every 5 s; scenes, messages, radio favourites and music channels every minute (they change
    rarely), and straight after Home Assistant changes one"""

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
                self._slow = {"scenes": await self.client.scenes(), "messages": await self.client.messages(),
                              "radio": await self._optional(self.client.radio), "channels": await self._optional(self.client.channels)}
                self._slow_t = time.monotonic()
            amps = (await self.client.amps()).get("amps", []) if state.get("amps") else []   # boxes from before: none
        except HostAuthError as e:
            raise ConfigEntryAuthFailed(str(e)) from e
        except HostError as e:
            raise UpdateFailed(str(e)) from e
        return {"state": state, "status": status, "amps": amps, **self._slow}

    @staticmethod
    async def _optional(fetch) -> dict | None:
        """a part an older processor may not have (or a fault in it): None, the rest still updates"""
        try:
            return await fetch()
        except HostAuthError:
            raise
        except HostError:
            return None

    def refresh_slow(self) -> None:
        self._slow_t = 0.0
