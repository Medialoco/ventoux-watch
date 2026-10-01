"""Remember repeated spots in this exact frame.

A lamp, a branch or the beacon comes back. After several times, the reading
changes from "unknown motion" to "a habit of the view". The count is kept
either way, so a repeated spot is not dropped from the record.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from watcher.naming import Decision

HABIT_AFTER = 8


class Memory:
    def __init__(self, path: Path):
        self.path = path
        self.state = {"seen": 0, "named": 0, "habits": 0, "cells": {}}
        full = path.with_name("learning-cells.json")
        source = full if full.is_file() else path
        if source.is_file():
            try:
                self.state.update(json.loads(source.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass

    def observe(self, zone: str, centroid: tuple[float, float], decision: Decision) -> str:
        """Return 'record' to keep a card, or 'count' when a habit was already shown."""
        self.state["seen"] = int(self.state.get("seen", 0)) + 1
        if decision.type not in {"motion", "habit"}:
            self.state["named"] = int(self.state.get("named", 0)) + 1
            self._write()
            return "record"
        key = f"{zone}:{round(centroid[0], 2)}:{round(centroid[1], 2)}"
        cells = self.state.setdefault("cells", {})
        cell = cells.setdefault(key, {"n": 0, "last": 0})
        cell["n"] = int(cell["n"]) + 1
        self.state["habits"] = sum(1 for item in cells.values() if int(item.get("n", 0)) >= HABIT_AFTER)
        if cell["n"] < HABIT_AFTER:
            self._write()
            return "record"
        decision.type = "habit"
        decision.label = "Habitude du cadrage"
        decision.reason = "repeated_spot"
        decision.detail["reading"] = (
            "Cet endroit a bougé plusieurs fois sans événement nouveau. "
            "Le cadrage le reconnaît maintenant."
        )
        cell["last"] = time.time()
        self._write()
        return "record"

    def _verdicts(self) -> dict:
        """The review tallies, read back from disk on every write.

        They are not ours. The review script increments them, and it runs while
        the watch runs; holding them in memory meant stamping back whatever
        they were at start-up, which erased each verdict a few seconds after it
        was given. Ninety-four of them had been given.

        Worse, the state is loaded from learning-cells.json, which the watch
        owns and which never carried these two keys at all — so the value held
        in memory was not even stale, it was zero.
        """
        try:
            disk = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"accepted": 0, "rejected": 0}
        return {"accepted": int(disk.get("accepted") or 0),
                "rejected": int(disk.get("rejected") or 0)}

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        public = {
            "seen": self.state.get("seen", 0),
            "named": self.state.get("named", 0),
            "habits": self.state.get("habits", 0),
            **self._verdicts(),
        }
        self.path.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        full = self.path.with_name("learning-cells.json")
        full.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
