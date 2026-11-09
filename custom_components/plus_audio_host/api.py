"""Plus Audio Host local API client (the box's own JSON API on the venue network).

Authentication: an access token made on the box (Settings > Access tokens), sent as X-BMP-Token. A staff token can
change zone source, volume (up to each zone's limit) and mute, run scenes and make announcements; that is all this
integration needs. Nothing here goes through the cloud.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class HostError(Exception):
    """the box answered with an error (message is safe to show)"""


class HostAuthError(HostError):
    """the token is wrong, revoked or lacks the scope"""


class HostClient:
    def __init__(self, session: aiohttp.ClientSession, url: str, token: str, verify_ssl: bool = False) -> None:
        self._s = session
        self.url = url.rstrip("/")
        self._token = token
        self._ssl = None if verify_ssl else False

    # for the live meters' websocket (meters.py)
    @property
    def session(self) -> aiohttp.ClientSession:
        return self._s

    @property
    def token(self) -> str:
        return self._token

    @property
    def ssl(self):
        return self._ssl

    async def _req(self, method: str, path: str, body: Any = None) -> Any:
        headers = {"X-BMP-Token": self._token}
        try:
            async with asyncio.timeout(10):
                async with self._s.request(method, self.url + path, json=body, headers=headers, ssl=self._ssl) as r:
                    try:
                        data = await r.json(content_type=None)
                    except ValueError:
                        data = {}
                    if r.status in (401, 403):
                        raise HostAuthError((data or {}).get("error") or "the access token was refused")
                    if r.status >= 400 or (isinstance(data, dict) and data.get("ok") is False):
                        raise HostError((data or {}).get("error") or f"HTTP {r.status}")
                    return data
        except (aiohttp.ClientError, TimeoutError) as e:
            raise HostError(f"can't reach the processor: {e}") from e

    # reads
    async def whoami(self) -> dict:
        return await self._req("GET", "/api/whoami")

    async def state(self) -> dict:
        return await self._req("GET", "/api/state")

    async def status(self) -> dict:
        return await self._req("GET", "/api/status")

    async def meters(self) -> dict:
        """the zones' live levels only (newer processors; older ones answer 404 and the meters use status())"""
        return await self._req("GET", "/api/meters")

    async def scenes(self) -> dict:
        return await self._req("GET", "/api/scenes")

    async def messages(self) -> dict:
        return await self._req("GET", "/api/messages")

    async def radio(self) -> dict:
        """the internet radio: favourite stations (what staff may play), the station playing"""
        return await self._req("GET", "/api/radio")

    async def channels(self) -> dict:
        """the music player's channels (Jamendo) and the one playing"""
        return await self._req("GET", "/api/jamendo")

    # changes
    async def set_zone(self, zone: int, **fields: Any) -> None:
        await self._req("PUT", f"/api/zones/{int(zone)}", fields)

    async def amps(self) -> dict:
        return await self._req("GET", "/api/amps")

    async def amp_power(self, amp_id: str, standby: bool) -> None:
        await self._req("POST", f"/api/amps/{amp_id}/power", {"standby": bool(standby)})

    async def set_group(self, group_id: str, **fields: Any) -> None:
        await self._req("PUT", f"/api/groups/{group_id}", fields)

    async def run_scene(self, scene_id: str) -> None:
        await self._req("POST", f"/api/scenes/{scene_id}/run", {})

    async def announce(self, zones: list[int], message_id: str | None = None, text: str | None = None, chime: bool | None = None) -> None:
        body: dict[str, Any] = {"zones": zones}
        if message_id:
            body["message_id"] = message_id
        else:
            body["text"] = text or ""
        if chime is not None:
            body["chime"] = chime
        await self._req("POST", "/api/announce", body)

    # the music player and the radio are one each per processor, shared by every zone that plays them
    async def player(self, cmd: str) -> None:
        """play | pause | next | prev"""
        await self._req("POST", "/api/player", {"cmd": cmd})

    async def play_channel(self, channel: str) -> None:
        """a channel id, or "local" for the music stored on the processor"""
        await self._req("POST", "/api/jamendo", {"channel": channel})

    async def play_station(self, station: str, zone: int | None = None) -> None:
        """a favourite station; with zone, that zone switches to the radio too"""
        body: dict[str, Any] = {"station": station}
        if zone is not None:
            body["zone"] = int(zone)
        await self._req("POST", "/api/radio", body)

    async def radio_cmd(self, cmd: str) -> None:
        """pause | play"""
        await self._req("POST", "/api/radio", {"cmd": cmd})

    async def stop_announcements(self) -> None:
        await self._req("POST", "/api/announce/stop", {})
