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


class RadioServeur:
    def __init__(self, racine_hls: Path) -> None:
        self.racine = racine_hls.resolve()
        self._serveur: ThreadingHTTPServer | None = None
        self._fil: threading.Thread | None = None

    def demarre(self, port: int) -> None:
        if self._serveur is not None:
            return
        racine = self.racine

        class Requete(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                return

            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
                self.send_header("Cache-Control", "no-store")

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                chemin = unquote(urlparse(self.path).path.lstrip("/"))
                if chemin == "":
                    chemin = HLS_INDEX
                cible = (racine / chemin).resolve()
                if not str(cible).startswith(str(racine)) or not cible.is_file():
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
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

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
