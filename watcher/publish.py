"""Push named events to GitHub at most every fifteen minutes."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("ventoux.publish")


def publish(repo: Path) -> bool:
    if not (repo / ".git").is_dir():
        log.info("Pas de dépôt git, publication ignorée")
        return False
    paths = [
        "data/events.json",
        "data/thumbs",
        "data/learning.json",
        "data/view.json",
        "data/view.jpg",
        # The register of blind spells travels with the history it explains.
        # Kept on the watching machine alone, it would be lost with the machine.
        "data/interruptions.jsonl",
        "data/reviewed.jsonl",
        # Ce que chaque décision a eu sous les yeux. Sans ce fichier, un verdict
        # rendu depuis un navigateur trois jours plus tard ne peut pas être
        # rejoué, et une faute réparée ne le reste pas.
        "data/observed.jsonl",
    ]
    try:
        # --autostash : la veille écrit dans data/ en permanence, et un rebase
        # refuse de démarrer sur un arbre sale. Sans cela le rapatriement échoue
        # à chaque tour, et le premier verdict rendu depuis le site — qui arrive
        # par le dépôt, pas par cette machine — fait diverger les deux côtés et
        # bloque toute publication ultérieure.
        _git(repo, "pull", "--rebase", "--autostash", "origin", "main")
    except subprocess.CalledProcessError as erreur:
        log.warning("Historique distant non rapatrié : %s", (erreur.stderr or "").strip()[:200])
    status = _git(repo, "status", "--porcelain", "--", *paths)
    if not status.strip():
        return False
    _git(repo, "add", "--", *paths)
    staged = _git(repo, "diff", "--cached", "--name-only")
    blocked = [line for line in staged.splitlines() if line.startswith("secrets/") or line.endswith(".json") and "drive" in line]
    if blocked:
        log.error("Refus de publier des secrets: %s", blocked)
        _git(repo, "reset", "HEAD")
        return False
    _git(repo, "commit", "-m", "Ajoute les événements nommés de la webcam")
    _git(repo, "push", "origin", "HEAD")
    log.info("Historique publié")
    return True


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout
