"""Flux audio HLS parallèle à YouTube, servi en HTTP pour le secours du site.

Le même mix que l'antenne (Dogmazic, voix, effets) part vers RTMP et, en
branche, vers des segments HLS sur le disque. Ce module sert la playlist et
écrit data/radio.json pour que la page sache où écouter quand YouTube tombe.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

log = logging.getLogger("ventoux.radio")

RADIO_JSON = "data/radio.json"
HLS_INDEX = "index.m3u8"
NOW_JSON = "now.json"
DIRECT_JSON = "data/direct.json"
DOGMUSIC_JSON = "data/dogmazic_playlist.json"
RADIO_PAGE = Path(__file__).with_name("radio_page.html")
SESSION_DATA = '#EXT-X-SESSION-DATA:DATA-ID="com.freetechnoradio.now",URI="now.json"'


def veut_page_html(accept: str) -> bool:
    """Navigateur : page d'écoute. Lecteur HLS : la playlist telle quelle."""
    entete = (accept or "").lower()
    if "application/vnd.apple.mpegurl" in entete:
        return False
    return "text/html" in entete


def _corps_page() -> bytes:
    return RADIO_PAGE.read_bytes()


def note_radio(racine: Path, *, live: bool, public_base: str) -> None:
    """État publié avec le reste : URL HTTPS du flux, pas les segments."""
    base = (public_base or "").rstrip("/")
    url = f"{base}/{HLS_INDEX}" if live and base else ""
    fichier = racine / RADIO_JSON
    fichier.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps({
        "live": bool(live and url),
        "url": url,
        "vu": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, ensure_ascii=False, indent=2)
    passage = fichier.with_suffix(".json.tmp")
    passage.write_text(texte + "\n", encoding="utf-8")
    passage.replace(fichier)


def titre_du_morceau(fiche: dict | None) -> str:
    """Artiste, titre et licence, sur une seule ligne de playlist.

    C'est la contrepartie de la licence, portée par le flux lui-même : un
    lecteur qui affiche le titre du segment en cours nomme l'œuvre, sans
    avoir à ouvrir la page.
    """
    if not fiche:
        return ""
    artiste = str(fiche.get("artiste") or fiche.get("auteur") or "")
    titre = str(fiche.get("titre") or "")
    licence = str(fiche.get("licence") or "")
    morceau = " — ".join(part.replace("\n", " ").strip() for part in (artiste, titre) if part.strip())
    licence = licence.replace("\n", " ").strip()
    if licence:
        return f"{morceau} · {licence}" if morceau else licence
    return morceau


def publie_morceau(dossier: Path, fiche: dict | None) -> None:
    """Écrit now.json à côté de la playlist. Le serveur s'en sert pour le titre."""
    if not fiche or not titre_du_morceau(fiche):
        return
    dossier.mkdir(parents=True, exist_ok=True)
    corps = {
        "artiste": str(fiche.get("auteur") or fiche.get("artiste") or "").strip(),
        "titre": str(fiche.get("titre") or "").strip(),
        "licence": str(fiche.get("licence") or "").strip(),
        "url": str(fiche.get("url") or "").strip(),
        "url_licence": str(fiche.get("url_licence") or "").strip(),
        "pochette": str(fiche.get("pochette") or "").strip(),
    }
    fichier = dossier / NOW_JSON
    texte = json.dumps(corps, ensure_ascii=False, indent=2) + "\n"
    passage = fichier.with_suffix(".json.tmp")
    passage.write_text(texte, encoding="utf-8")
    passage.replace(fichier)


def habille_playlist(texte: str, titre: str) -> str:
    """Pose le crédit sur chaque segment, et pointe vers now.json."""
    if not titre:
        return texte
    lignes: list[str] = []
    pose = False
    for ligne in texte.splitlines():
        if ligne.startswith("#EXTINF:"):
            duree = ligne.split(":", 1)[1].split(",", 1)[0]
            lignes.append(f"#EXTINF:{duree},{titre}")
            continue
        lignes.append(ligne)
        if not pose and ligne.startswith("#EXT-X-VERSION"):
            lignes.append(SESSION_DATA)
            pose = True
    if not pose:
        lignes.insert(1, SESSION_DATA)
    return "\n".join(lignes) + "\n"


def _playlist_habillée(racine: Path, brut: bytes) -> bytes:
    try:
        fiche = json.loads((racine / NOW_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return brut
    titre = titre_du_morceau(fiche if isinstance(fiche, dict) else None)
    if not titre:
        return brut
    return habille_playlist(brut.decode("utf-8", "replace"), titre).encode("utf-8")


class RadioServeur:
    def __init__(
        self,
        racine_hls: Path,
        pochettes: Path | None = None,
        racine_watch: Path | None = None,
    ) -> None:
        self.racine = racine_hls.resolve()
        self.pochettes = pochettes.resolve() if pochettes else None
        self.racine_watch = racine_watch.resolve() if racine_watch else None
        self._serveur: ThreadingHTTPServer | None = None
        self._fil: threading.Thread | None = None

    def demarre(self, port: int) -> None:
        if self._serveur is not None:
            return
        racine = self.racine
        dossier_pochettes = self.pochettes
        projet = self.racine_watch

        class Requete(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                return

            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
                self.send_header("Cache-Control", "no-store")

            def _envoie(self, code: int, mime: str, corps: bytes) -> None:
                self.send_response(code)
                self._cors()
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(corps)

            def _page(self) -> None:
                if not RADIO_PAGE.is_file():
                    self.send_response(404)
                    self._cors()
                    self.end_headers()
                    return
                self._envoie(200, "text/html; charset=utf-8", _corps_page())

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_HEAD(self) -> None:  # noqa: N802
                self.do_GET()

            def do_GET(self) -> None:  # noqa: N802
                chemin = unquote(urlparse(self.path).path.lstrip("/"))
                accept = self.headers.get("Accept", "")

                if chemin in ("", "listen", "index.html"):
                    self._page()
                    return
                if chemin == HLS_INDEX and veut_page_html(accept):
                    self._page()
                    return
                if chemin in ("direct.json", "dogmazic.json") and projet is not None:
                    rel = DIRECT_JSON if chemin == "direct.json" else DOGMUSIC_JSON
                    cible = (projet / rel).resolve()
                    if not str(cible).startswith(str(projet)) or not cible.is_file():
                        self.send_response(404)
                        self._cors()
                        self.end_headers()
                        return
                    self._envoie(200, "application/json; charset=utf-8", cible.read_bytes())
                    return
                if chemin.startswith("pochettes/") and dossier_pochettes is not None:
                    rel = chemin.split("/", 1)[1]
                    cible = (dossier_pochettes / rel).resolve()
                    autorisé = str(cible).startswith(str(dossier_pochettes))
                else:
                    cible = (racine / chemin).resolve()
                    autorisé = str(cible).startswith(str(racine))
                if not autorisé or not cible.is_file():
                    self.send_response(404)
                    self._cors()
                    self.end_headers()
                    return
                mime = mimetypes.guess_type(cible.name)[0]
                if cible.suffix == ".m3u8":
                    mime = "application/vnd.apple.mpegurl"
                elif cible.suffix == ".ts":
                    mime = "video/mp2t"
                corps = cible.read_bytes()
                if cible.name == HLS_INDEX:
                    corps = _playlist_habillée(racine, corps)
                self._envoie(200, mime or "application/octet-stream", corps)

        ThreadingHTTPServer.allow_reuse_address = True
        self._serveur = ThreadingHTTPServer(("0.0.0.0", port), Requete)
        self._fil = threading.Thread(target=self._serveur.serve_forever, daemon=True)
        self._fil.start()
        log.info("Radio HLS servie sur le port %d (%s)", port, self.racine)

    def ferme(self) -> None:
        if self._serveur is not None:
            self._serveur.shutdown()
            self._serveur.server_close()
            self._serveur = None
