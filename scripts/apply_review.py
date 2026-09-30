"""Apply a validation issue to the event history. Used by GitHub Actions."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Tous les scripts d'à côté font cette ligne ; celui-ci l'avait oubliée, et
# c'est le seul qui tourne sans personne pour le regarder. « python
# scripts/apply_review.py » met scripts/ dans le chemin d'import, pas la
# racine, donc « watcher » est introuvable. Onze verdicts sont tombés là.
sys.path.insert(0, str(ROOT))

from watcher.review import apply_files, parse_review  # noqa: E402


def main() -> int:
    parsed = parse_review(os.environ.get("ISSUE_BODY", ""), os.environ.get("LABEL", ""))
    if parsed is None:
        print("missing")
        return 0
    event_id, verdict, classe = parsed
    if apply_files(ROOT, event_id, verdict, classe):
        print(f"updated {event_id} {verdict} {classe}".rstrip())
        return 0
    print("unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
