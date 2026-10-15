"""Push named events to GitHub at most every fifteen minutes."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("ventoux.publish")

# L'état de l'antenne, que cette machine seule écrit. Un pull dont l'autostash
# bute sur un conflit laisse la version du dépôt à la place : le 15 octobre,
# direct.json est ainsi revenu au direct mort pendant que le neuf tournait.
ETAT_LOCAL = ("data/direct.json", "data/antenne.json", "data/radio.json")


def garde_etat(repo: Path) -> dict[str, bytes]:
    gardes = {}
    for nom in ETAT_LOCAL:
        try:
            gardes[nom] = (repo / nom).read_bytes()
        except OSError:
            pass
    return gardes


def rend_etat(repo: Path, gardes: dict[str, bytes]) -> None:
    """Remet l'état gardé, seulement là où git l'a remplacé par le sien.

    Un fichier qui ne vaut ni l'état gardé ni la version du dépôt a été
    réécrit entre-temps par l'antenne : c'est lui le plus frais.
    """
    for nom, contenu in gardes.items():
        fichier = repo / nom
        try:
            actuel = fichier.read_bytes()
        except OSError:
            actuel = None
        if actuel == contenu:
            continue
        if actuel is not None:
            depot = subprocess.run(["git", "show", f"HEAD:{nom}"], cwd=repo,
                                   capture_output=True, check=False).stdout
            if actuel != depot:
                continue
        passage = fichier.with_suffix(fichier.suffix + ".tmp")
        passage.write_bytes(contenu)
        passage.replace(fichier)


def publish(repo: Path) -> bool:
    if not (repo / ".git").is_dir():
        log.info("Pas de dépôt git, publication ignorée")
        return False
    paths = [
        "data/events.json",
        # Les deux images, et nettes. La vue d'ensemble dit où la chose est
        # passée, la découpe dit ce que c'était, et qui juge a besoin des deux :
        # un car dont on ne lit plus le flanc n'est plus jugeable. Le floutage
        # existe, mais il est posé à l'antenne, à l'instant de rejouer un
        # passage devant des gens qui ne l'ont pas demandé — pas ici, où l'on
        # vient chercher une image pour l'examiner.
        "data/thumbs",
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
        # Le numéro du direct en cours. Il change chaque fois que YouTube
        # termine la diffusion et qu'on en rouvre une ; une page qui l'écrirait
        # en dur finirait par incruster un enregistrement fini.
        "data/direct.json",
        "data/antenne.json",
        "data/radio.json",
    ]
    gardes = garde_etat(repo)
    try:
        # --autostash : la veille écrit dans data/ en permanence, et un rebase
        # refuse de démarrer sur un arbre sale. Sans cela le rapatriement échoue
        # à chaque tour, et le premier verdict rendu depuis le site — qui arrive
        # par le dépôt, pas par cette machine — fait diverger les deux côtés et
        # bloque toute publication ultérieure.
        _git(repo, "pull", "--rebase", "--autostash", "origin", "main")
    except subprocess.CalledProcessError as erreur:
        log.warning("Historique distant non rapatrié : %s", (erreur.stderr or "").strip()[:200])
    rend_etat(repo, gardes)
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
