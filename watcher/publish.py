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
        # Plus les vignettes de la vue d'ensemble.
        #
        # Analyser automatiquement un flux auquel on accède licitement est une
        # chose, et une chose prévue. En pousser chaque jour cinquante
        # mégaoctets de captures dans un dépôt public en est une autre : c'est
        # une photothèque de la webcam constituée à côté d'elle, et ni la
        # fouille de données ni rien d'autre ne l'autorise. Celles déjà
        # publiées restent, elles sont dans l'histoire du dépôt ; il n'en part
        # plus de nouvelles.
        #
        # Ce qui part à leur place est la découpe du sujet, en gros blocs gris.
        # Elle dit ce que l'historique a à dire — quelque chose est passé là, à
        # cette heure — sans reproduire l'image ni montrer personne.
        # La découpe que le modèle a vue, gardée à la résolution de la source.
        # La vignette fait 480 pixels de large pour une image de 1920 : une
        # voiture au rond-point y tient sur trente pixels, de quoi voir qu'il
        # s'est passé quelque chose, pas de quoi dire quoi — et c'est
        # exactement ce qu'on demande à qui juge une carte. Douze mégaoctets
        # pour huit cents découpes, contre soixante-cinq de vignettes déjà
        # poussées, et « prune » les efface au même moment que la vignette.
        # La découpe publiée est pixellisée et en gris : on y voit qu'une
        # chose est passée, jamais qui. Les originaux nets restent sur la
        # machine qui veille, dans un dossier que git ignore.
        "data/closeups",
        "data/learning.json",
        "data/view.json",
        "data/view.jpg",
        # The register of blind spells travels with the history it explains.
        # Kept on the watching machine alone, it would be lost with the machine.
        "data/interruptions.jsonl",
        # Le relevé de la jauge de brouillard dans le temps. Même raison : le
        # seuil qui fait taire la veille la nuit ne pourra être réécrit sur des
        # mesures que si les mesures voyagent avec l'historique.
        "data/crete.jsonl",
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
