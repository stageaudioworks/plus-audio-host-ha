"""Amplifiers the Host controls (Plus Audio AC403 / AC401): entities are made as amplifiers appear on the box (the
next update after one is added) and go unavailable when one is removed. Boxes from before amplifiers have none."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import Entity

from .coordinator import HostCoordinator
from .entity import HostEntity


def follow_amps(coord: HostCoordinator, entry: ConfigEntry, add: Callable[[Iterable[Entity]], None],
                make: Callable[[HostCoordinator, str], Entity]) -> None:
    known: set[str] = set()

    def fresh() -> None:
        new = [a["id"] for a in coord.data.get("amps") or [] if a["id"] not in known]
        known.update(new)
        if new:
            add(make(coord, aid) for aid in new)

    fresh()
    entry.async_on_unload(coord.async_add_listener(fresh))


class AmpEntity(HostEntity):
    def __init__(self, coord: HostCoordinator, aid: str, key: str) -> None:
        super().__init__(coord, f"amp_{aid}_{key}")
        self._aid = aid

    @property
    def _a(self) -> dict:
        return next((a for a in self.coordinator.data.get("amps") or [] if a["id"] == self._aid), {})

    @property
    def _s(self) -> dict:
        return self._a.get("status") or {}

    @property
    def available(self) -> bool:
        return super().available and bool(self._a)
