"""Live zone meters for dashboards, at up to 20 updates a second, without touching entities or the recorder.

A dashboard card (the bundled "Plus Audio meters" card) subscribes over Home Assistant's own websocket
(`plus_audio_host/meters/subscribe`). While at least one card is open, a hub per processor fetches the levels and
pushes them to every subscriber; with no card open it does nothing, so the processor and Home Assistant only do this
work while someone is looking. The browser never talks to the processor and never sees its token.

Where the levels come from, best first (the hub picks the first the processor offers, and checks again after a
failure):
1. push: a websocket at /api/meters/ws that sends {"zones": [...]} frames by itself (a Host feature, see METERS.md)
2. a light poll: GET /api/meters, {"zones": [...]} (a Host feature, see METERS.md)
3. the full status every processor has: GET /api/status, its "zones" (works today; slower to fetch)

Each zone in a frame: {"zone": 1, "peak_db": [left, right], "rms_db": [left, right] (optional), "active": bool}.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback

from .api import HostAuthError, HostError
from .const import METER_MAX_HZ

_LOG = logging.getLogger(__name__)

SILENT = -120.0


def _db_list(v: Any) -> list[float]:
    if v is None:
        return []
    if isinstance(v, (int, float)):
        return [float(v)]
    try:
        return [float(x) if x is not None else SILENT for x in v]
    except (TypeError, ValueError):
        return []


class MeterHub:
    """one per processor; runs only while subscribers exist"""

    def __init__(self, hass: HomeAssistant, coord) -> None:
        self.hass = hass
        self.coord = coord
        self._subs: dict[int, tuple[Callable[[dict], None], float]] = {}
        self._next = 0
        self._task: asyncio.Task | None = None
        self.mode: str | None = None          # "push", "meters", "status": what the processor offered last
        self._no_push_until = 0.0
        self._no_meters_until = 0.0

    # ---- subscribers
    @callback
    def subscribe(self, cb: Callable[[dict], None], rate: float = 10.0) -> Callable[[], None]:
        self._next += 1
        key = self._next
        self._subs[key] = (cb, max(1.0, min(METER_MAX_HZ, float(rate))))
        cb(self._frame([], self.mode or "starting"))         # names and layout straight away, levels follow
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_background_task(self._run(), f"plus_audio_host meters {self.coord.config_entry.entry_id}")

        @callback
        def unsub() -> None:
            self._subs.pop(key, None)
            if not self._subs and self._task and not self._task.done():
                self._task.cancel()
        return unsub

    @callback
    def close(self) -> None:
        """the processor's entry is unloading: stop, and send open cards nothing more"""
        self._subs.clear()
        if self._task and not self._task.done():
            self._task.cancel()

    @property
    def _interval(self) -> float:
        return 1.0 / max((r for _, r in self._subs.values()), default=10.0)

    def _send(self, frame: dict) -> None:
        for cb, _ in list(self._subs.values()):
            try:
                cb(frame)
            except Exception:                  # a closed connection must not stop the others
                _LOG.debug("meter subscriber failed", exc_info=True)

    # ---- frames
    def _frame(self, zones: list[dict], mode: str) -> dict:
        """the zones in use, in order, with names from the last full update; levels where the processor sent them"""
        live = {z.get("zone"): z for z in zones if isinstance(z, dict)}
        state = (self.coord.data or {}).get("state") or {}
        out = []
        for z in state.get("zones", []):
            if z.get("in_use", True) is False:
                continue
            m = live.get(z["id"], {})
            out.append({"zone": z["id"], "letter": chr(64 + z["id"]), "name": z.get("name") or f"Zone {chr(64 + z['id'])}",
                        "source": z.get("source"), "mute": bool(z.get("mute")),
                        "peak_db": _db_list(m.get("peak_db")), "rms_db": _db_list(m.get("rms_db")), "active": m.get("active")})
        return {"entry_id": self.coord.config_entry.entry_id, "device": state.get("device_name") or "Plus Audio Host",
                "mode": mode, "t": time.time(), "zones": out}

    # ---- the loop
    async def _run(self) -> None:
        try:
            while self._subs:
                now = time.monotonic()
                try:
                    if now >= self._no_push_until and await self._push():
                        continue                    # the push ended (closed, or every card went): decide again
                    if now >= self._no_meters_until:
                        await self._poll("meters")
                    else:
                        await self._poll("status")
                except HostAuthError as e:
                    self._send({**self._frame([], "error"), "error": str(e)})
                    await asyncio.sleep(10)
                except HostError as e:
                    self._send({**self._frame([], "error"), "error": str(e)})
                    await asyncio.sleep(2)
        except asyncio.CancelledError:
            pass
        finally:
            self.mode = None

    async def _push(self) -> bool:
        """the processor's own push, while it lasts; False when it has none (then don't ask again for 10 minutes)"""
        c = self.coord.client
        url = c.url.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/api/meters/ws"
        try:
            async with c.session.ws_connect(url, headers={"X-BMP-Token": c.token}, ssl=c.ssl, heartbeat=15,
                                            timeout=aiohttp.ClientWSTimeout(ws_close=5)) as ws:
                self.mode = "push"
                min_gap, last = self._interval, 0.0
                async for msg in ws:
                    if not self._subs:
                        return True
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                        continue
                    t = time.monotonic()
                    if t - last < min_gap * 0.8:       # the processor may send faster than any card asked for
                        continue
                    last = t
                    data = msg.json()
                    self._send(self._frame(data.get("zones") or [], "push"))
                return True
        except aiohttp.WSServerHandshakeError as e:
            if e.status in (401, 403):
                raise HostAuthError("the access token was refused") from e
            self._no_push_until = time.monotonic() + 600       # no push on this processor (404 and the like)
            return False
        except (aiohttp.ClientError, TimeoutError, ValueError):
            self._no_push_until = time.monotonic() + 60
            return False

    async def _poll(self, how: str) -> None:
        c = self.coord.client
        start = time.monotonic()
        if how == "meters":
            try:
                data = await c.meters()
            except HostAuthError:
                raise
            except HostError:
                self._no_meters_until = time.monotonic() + 600    # no /api/meters on this processor: use the status
                return
        else:
            data = await c.status()
        self.mode = how
        self._send(self._frame((data or {}).get("zones") or [], how))
        await asyncio.sleep(max(0.0, self._interval - (time.monotonic() - start)))
