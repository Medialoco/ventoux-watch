"""Rouvrir le direct YouTube sans passer par la salle de contrôle.

Sur dix jours de novembre, la chaîne a perdu son direct dix fois. Le Pi a
continué de pousser les images vers la clé, et YouTube n'a jamais rouvert de
diffusion de lui-même : il a fallu, à chaque fois, ouvrir YouTube Studio. Le
direct est resté noir de quarante minutes à plusieurs heures.

Ce module fait le geste de Studio par l'API YouTube Data : trouver le flux de
notre clé, créer une diffusion qui démarre seule et ne s'arrête pas seule,
l'attacher au flux, et la passer en direct si YouTube ne l'a pas fait.

L'autorisation se donne une fois, sur le Mac, avec scripts/youtube_autorise.py.
Elle s'écrit dans « secrets/youtube_oauth.json », que git ignore. Sans ce
fichier, rien ne se passe : la veille du direct continue comme avant.

Seule la bibliothèque standard sert ici, pour ne rien installer sur le Pi.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger("youtube_api")

JETON_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
PORTEE = "https://www.googleapis.com/auth/youtube"
DELAI_S = 20
TITRE_DEFAUT = ("#FreeTechnoRadio 24/7 CC over THE Webcam at #MontSerein "
                "#MontVentoux - #Cannes more than a backup ❤️")
# Le temps qu'on laisse au démarrage automatique avant de forcer le direct.
ATTENTE_DEPART_S = 60.0
ATTENTE_PAS_S = 10.0

# (méthode, url, données ou None, en-têtes) -> corps de la réponse
Ouvreur = Callable[[str, str, bytes | None, dict], bytes]


def _ouvre(methode: str, url: str, donnees: bytes | None, entetes: dict) -> bytes:
    requete = urllib.request.Request(url, data=donnees, method=methode, headers=entetes)
    with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
        return reponse.read()


def autorisation(racine: Path) -> dict | None:
    chemin = racine / "secrets" / "youtube_oauth.json"
    try:
        oauth = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if all(oauth.get(c) for c in ("client_id", "client_secret", "refresh_token")):
        return oauth
    return None


def cle_de_flux(racine: Path) -> str:
    try:
        local = json.loads((racine / "config" / "local.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str((local.get("youtube") or {}).get("key") or "")


def jeton(oauth: dict, ouvre: Ouvreur = _ouvre) -> str:
    corps = urllib.parse.urlencode({
        "client_id": oauth["client_id"],
        "client_secret": oauth["client_secret"],
        "refresh_token": oauth["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    reponse = json.loads(ouvre("POST", JETON_URL, corps,
                               {"Content-Type": "application/x-www-form-urlencoded"}))
    return reponse["access_token"]


class Api:
    def __init__(self, acces: str, ouvre: Ouvreur = _ouvre) -> None:
        self.acces = acces
        self.ouvre = ouvre

    def appel(self, methode: str, chemin: str, params: dict,
              corps: dict | None = None) -> dict:
        url = f"{API}/{chemin}?{urllib.parse.urlencode(params)}"
        entetes = {"Authorization": f"Bearer {self.acces}"}
        donnees = None
        if corps is not None:
            donnees = json.dumps(corps).encode()
            entetes["Content-Type"] = "application/json"
        elif methode == "POST":
            donnees = b""
        brut = self.ouvre(methode, url, donnees, entetes)
        return json.loads(brut) if brut else {}

    def flux_de_la_cle(self, cle: str) -> str | None:
        reponse = self.appel("GET", "liveStreams",
                             {"part": "id,cdn", "mine": "true", "maxResults": 50})
        for flux in reponse.get("items") or []:
            nom = ((flux.get("cdn") or {}).get("ingestionInfo") or {}).get("streamName")
            if nom == cle:
                return flux["id"]
        return None

    def diffusions(self, etat: str, parts: str = "id,snippet,status,contentDetails",
                   combien: int = 50) -> list[dict]:
        reponse = self.appel("GET", "liveBroadcasts", {
            "part": parts, "broadcastStatus": etat,
            "broadcastType": "all", "maxResults": combien})
        return reponse.get("items") or []

    def cree(self, titre: str, description: str, visibilite: str) -> str:
        maintenant = datetime.now(timezone.utc).isoformat(timespec="seconds")
        reponse = self.appel("POST", "liveBroadcasts",
                             {"part": "snippet,status,contentDetails"}, {
            "snippet": {"title": titre[:100], "description": description,
                        "scheduledStartTime": maintenant},
            "status": {"privacyStatus": visibilite,
                       "selfDeclaredMadeForKids": False},
            "contentDetails": {"enableAutoStart": True, "enableAutoStop": False,
                               "monitorStream": {"enableMonitorStream": False}},
        })
        return reponse["id"]

    def attache(self, diffusion: str, flux: str) -> None:
        self.appel("POST", "liveBroadcasts/bind",
                   {"id": diffusion, "part": "id,contentDetails", "streamId": flux})

    def etat(self, diffusion: str) -> str:
        reponse = self.appel("GET", "liveBroadcasts", {"part": "status", "id": diffusion})
        items = reponse.get("items") or []
        return str(((items[0] if items else {}).get("status") or {})
                   .get("lifeCycleStatus") or "")

    def en_direct(self, diffusion: str) -> None:
        self.appel("POST", "liveBroadcasts/transition",
                   {"broadcastStatus": "live", "id": diffusion, "part": "status"})


def _sur_notre_flux(diffusions: list[dict], flux: str) -> dict | None:
    for diffusion in diffusions:
        if (diffusion.get("contentDetails") or {}).get("boundStreamId") == flux:
            return diffusion
    return None


def rouvre(racine: Path, ouvre: Ouvreur = _ouvre,
           dort: Callable[[float], None] = time.sleep) -> str | None:
    """Le numéro de la diffusion en direct sur notre clé, rouverte s'il le faut.

    None quand on ne peut rien faire : pas d'autorisation, clé inconnue de la
    chaîne, ou YouTube qui refuse. Rien ici ne lève : c'est appelé depuis la
    veille du direct, qui doit continuer quoi qu'il arrive.
    """
    oauth = autorisation(racine)
    cle = cle_de_flux(racine)
    if oauth is None or not cle:
        return None
    try:
        api = Api(jeton(oauth, ouvre), ouvre)
        flux = api.flux_de_la_cle(cle)
        if flux is None:
            log.error("Aucun flux de la chaîne ne porte notre clé : rien à rouvrir")
            return None
        deja = _sur_notre_flux(api.diffusions("active"), flux)
        if deja is not None:
            log.info("Une diffusion est déjà en direct sur notre flux : %s", deja["id"])
            return deja["id"]
        # Une diffusion prévue et déjà attachée sert plutôt que d'en empiler.
        prevue = _sur_notre_flux(api.diffusions("upcoming"), flux)
        if prevue is not None:
            diffusion = prevue["id"]
            log.warning("On reprend la diffusion prévue %s", diffusion)
        else:
            modele = api.diffusions("completed", parts="snippet,status", combien=1)
            snippet = (modele[0].get("snippet") or {}) if modele else {}
            statut = (modele[0].get("status") or {}) if modele else {}
            diffusion = api.cree(snippet.get("title") or TITRE_DEFAUT,
                                 snippet.get("description") or "",
                                 statut.get("privacyStatus") or "public")
            api.attache(diffusion, flux)
            log.warning("Diffusion %s créée et attachée à notre flux", diffusion)
        attendu = 0.0
        while attendu < ATTENTE_DEPART_S:
            if api.etat(diffusion) in ("live", "liveStarting"):
                log.warning("Direct rouvert par l'API : %s", diffusion)
                return diffusion
            dort(ATTENTE_PAS_S)
            attendu += ATTENTE_PAS_S
        api.en_direct(diffusion)
        log.warning("Direct forcé par l'API : %s", diffusion)
        return diffusion
    except urllib.error.HTTPError as erreur:
        detail = erreur.read().decode("utf-8", "replace")[:300]
        log.error("YouTube refuse de rouvrir le direct (%s) : %s", erreur.code, detail)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as erreur:
        log.error("Direct non rouvert : %s", erreur)
    return None
