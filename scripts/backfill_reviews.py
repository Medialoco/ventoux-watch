"""Turn every correction given by hand into a row of the learning file.

Before the review buttons existed, a wrong reading was mended by editing the
history: the entry was renamed, its rectangle redrawn, or it was dropped
outright, and what we had learnt stayed in the comments of fix_history.py.
That is a poor place for it. Read straight, those ninety-odd judgements are
the only corpus we have of this camera being wrong, and each one carries the
measurements that produced the mistake.

The label the watcher first published is no longer in the history — the
correction overwrote it. It is recovered from git, by walking every version of
data/events.json back to the first and keeping the oldest form of each entry.
Nothing here is invented: an entry we cannot find in git is reported as
unresolved rather than guessed at.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.review import lesson  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from fix_history import DROP, REFRAME, RENAME  # noqa: E402

OUT = ROOT / "data" / "reviewed.jsonl"


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ""


def first_published() -> dict[str, dict]:
    """The oldest form of every entry that ever stood in the history.

    Walked newest to oldest and overwritten as it goes, so what survives is
    what the watcher wrote before any human touched it.
    """
    oldest: dict[str, dict] = {}
    commits = _git("log", "--format=%H", "--", "data/events.json").split()
    for index, sha in enumerate(commits):
        blob = _git("show", f"{sha}:data/events.json")
        if not blob:
            continue
        try:
            events = json.loads(blob).get("events") or []
        except json.JSONDecodeError:
            continue
        for event in events:
            when = event.get("t") or event.get("at")
            if when:
                oldest[when] = event
        if index % 100 == 0:
            print(f"  {index}/{len(commits)} versions lues, {len(oldest)} entrées", flush=True)
    return oldest


def main() -> int:
    now = {event["t"]: event for event in json.loads((ROOT / "data" / "events.json").read_text())["events"]}
    print(f"{len(now)} entrées dans l'historique, lecture de git…", flush=True)
    born = first_published()
    print(f"{len(born)} entrées retrouvées dans git", flush=True)

    rows, missing = [], []

    def add(when: str, verdict: str, truth: str, note: str) -> None:
        # The measurements and the photo are taken from the entry as it stands
        # now when it is still there, since the corrections kept them; what the
        # watcher had guessed can only come from git.
        source = now.get(when) or born.get(when)
        if source is None:
            missing.append(when)
            return
        row = lesson(source, verdict, "", (born.get(when) or source).get("label", ""), note=note)
        row["at"] = when
        row["truth"] = truth
        rows.append(row)

    for when, (_, label, *_rest) in RENAME.items():
        add(when, "accepted", label, "renommé à la main")
    for when, fix in REFRAME.items():
        # Some of these only moved the rectangle: the name was right, and the
        # truth is the name that still stands.
        truth = fix.get("label") or (now.get(when) or {}).get("label", "")
        add(when, "accepted", truth, "rectangle posé sur autre chose que le sujet")
    for when, why in DROP.items():
        add(when, "rejected", "", why)

    rows.sort(key=lambda row: row["at"])
    with OUT.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    kept = sum(1 for row in rows if row["measured"])
    print(f"\n{len(rows)} leçons écrites dans {OUT.relative_to(ROOT)}")
    print(f"  dont {kept} avec les mesures du moment")
    print(f"  rejets : {sum(1 for row in rows if row['verdict'] == 'rejected')}")
    if missing:
        print(f"  introuvables dans git ({len(missing)}) : {', '.join(sorted(missing))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
