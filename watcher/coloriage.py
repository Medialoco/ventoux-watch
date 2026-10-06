"""Le coloriage du cadre, touche après touche, pour une diffusion plus tard.

L'iPad n'écrit pas dans le direct. Il envoie une touche. Elle est notée, avec
son heure, et elle apparaît sur l'aperçu de la page. L'image qui part vers
YouTube n'en reçoit aucune : le geste est gardé pour être rediffusé plus tard,
dans le temps, et non posé d'un coup.

Le rouge du direct n'est pas dans la palette : ce rouge dit « en ce moment »,
et une touche de la même couleur le ferait mentir.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

# À la largeur de référence. Assez petit pour une touche, assez grand pour
# qu'on la voie encore une fois le cadre encodé.
RAYON = 11
PORT = 8766

# BGR, les mêmes teintes que le flux, sauf le rouge du badge.
COULEURS = {
    "cyan": (235, 215, 70),
    "ambre": (60, 190, 250),
    "vert": (120, 230, 130),
    "blanc": (245, 245, 245),
    "jaune": (40, 230, 250),
    "bleu": (200, 120, 40),
}

PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Coloriage</title>
<style>
  html, body { margin: 0; height: 100%; background: #000; color: #eee;
    font: 15px sans-serif; touch-action: none; }
  body { display: flex; flex-direction: column; }
  img { flex: 1; width: 100%; object-fit: contain; touch-action: none; }
  .note { margin: 0; padding: 8px 10px 0; color: #aaa; font-size: 13px; }
  .barre { display: flex; gap: 8px; padding: 10px; align-items: center;
    background: #111; }
  button { min-width: 44px; min-height: 44px; border: 3px solid transparent;
    border-radius: 8px; }
  button.on { border-color: #fff; }
  button.texte { color: #eee; background: #222; padding: 0 12px; }
</style>
</head>
<body>
<img id="cadre" alt="">
<p class="note">Plus tard. Pas sur le direct.</p>
<div class="barre" id="barre"></div>
<script>
const jeton = new URLSearchParams(location.search).get("j") || "";
const couleurs = COULEURS_JSON;
let couleur = couleurs[0][0];
let dernier = null;
const img = document.getElementById("cadre");
const barre = document.getElementById("barre");
couleurs.forEach(([nom, css]) => {
  const b = document.createElement("button");
  b.style.background = css;
  b.title = nom;
  b.className = nom === couleur ? "on" : "";
  b.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    couleur = nom;
    barre.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
  });
  barre.appendChild(b);
});
const efface = document.createElement("button");
efface.className = "texte";
efface.textContent = "Effacer";
efface.addEventListener("pointerdown", (ev) => {
  ev.preventDefault();
  ev.stopPropagation();
  fetch("/efface?j=" + encodeURIComponent(jeton), {method: "POST"});
});
barre.appendChild(efface);
function point(ev) {
  const r = img.getBoundingClientRect();
  const iw = img.naturalWidth || r.width;
  const ih = img.naturalHeight || r.height;
  const echelle = Math.min(r.width / iw, r.height / ih);
  const dw = iw * echelle, dh = ih * echelle;
  const ox = r.left + (r.width - dw) / 2;
  const oy = r.top + (r.height - dh) / 2;
  const x = (ev.clientX - ox) / dw;
  const y = (ev.clientY - oy) / dh;
  if (x < 0 || y < 0 || x > 1 || y > 1) return null;
  return {x, y};
}
function envoie(ev) {
  const p = point(ev);
  if (!p) return;
  if (dernier && Math.hypot(p.x - dernier.x, p.y - dernier.y) < 0.012) return;
  dernier = p;
  fetch("/touche?j=" + encodeURIComponent(jeton), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({x: p.x, y: p.y, couleur}),
  });
}
img.addEventListener("pointerdown", (ev) => { ev.preventDefault(); dernier = null; envoie(ev); });
img.addEventListener("pointermove", (ev) => { if (ev.buttons || ev.pointerType === "touch") envoie(ev); });
function rafraichit() {
  img.src = "/cadre.jpg?j=" + encodeURIComponent(jeton) + "&t=" + Date.now();
}
setInterval(rafraichit, 250);
rafraichit();
</script>
</body>
</html>
"""


def _css(bgr: tuple[int, int, int]) -> str:
    bleu, vert, rouge = bgr
    return f"#{rouge:02x}{vert:02x}{bleu:02x}"


PAGE = PAGE.replace(
    "COULEURS_JSON",
    json.dumps([[nom, _css(teinte)] for nom, teinte in COULEURS.items()]),
)


class Coloriage:
    """Les touches reçues depuis l'ouverture, dessinées quand leur heure arrive."""

    def __init__(self, journal: Path | None = None) -> None:
        self.journal = journal
        self._touches: list[tuple[float, float, float, tuple[int, int, int]]] = []
        self._verrou = threading.Lock()
        self._jpeg = b""
        self._apercu = 0.0
        self._jeton = ""
        self._serveur: ThreadingHTTPServer | None = None
        self._fil: threading.Thread | None = None

    def pose(self, x: float, y: float, nom: str, quand: float) -> bool:
        teinte = COULEURS.get(nom)
        if teinte is None:
            return False
        try:
            x = min(1.0, max(0.0, float(x)))
            y = min(1.0, max(0.0, float(y)))
        except (TypeError, ValueError):
            return False
        touche = (float(quand), x, y, teinte)
        with self._verrou:
            self._touches.append(touche)
        self._note({"t": touche[0], "x": x, "y": y, "couleur": nom})
        return True

    def efface(self) -> None:
        with self._verrou:
            self._touches.clear()
        self._note({"t": time.time(), "efface": True})

    def _note(self, ligne: dict) -> None:
        """Le geste, pour la diffusion plus tard. Un échec d'écriture n'arrête pas le flux."""
        if self.journal is None:
            return
        try:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            with self.journal.open("a", encoding="utf-8") as fichier:
                fichier.write(json.dumps(ligne) + "\n")
        except OSError:
            pass

    def dessine(self, image: np.ndarray, quand: float) -> None:
        """Pose les touches dont l'heure est déjà passée. Les autres attendent."""
        with self._verrou:
            lot = [touche for touche in self._touches if touche[0] <= quand]
        if not lot:
            return
        hauteur, largeur = image.shape[:2]
        rayon = max(2, int(round(RAYON * largeur / 1600)))
        for _quand, x, y, teinte in lot:
            cv2.circle(image, (int(x * (largeur - 1)), int(y * (hauteur - 1))),
                       rayon, teinte, -1, cv2.LINE_AA)

    def retiens(self, image: np.ndarray, quand: float, periode: float = 0.25) -> None:
        """Garde un aperçu pour l'iPad, pas à chaque image."""
        if quand - self._apercu < periode:
            return
        self._apercu = quand
        ok, tampon = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        if not ok:
            return
        with self._verrou:
            self._jpeg = tampon.tobytes()

    def ouvre(self, jeton: str, port: int = PORT) -> None:
        self._jeton = jeton
        coloriage = self

        class Requete(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                return

            def _autorise(self) -> bool:
                demande = urlparse(self.path)
                recu = (parse_qs(demande.query).get("j") or [""])[0]
                return recu == coloriage._jeton and bool(coloriage._jeton)

            def _refuse(self) -> None:
                self.send_response(403)
                self.end_headers()

            def do_GET(self):  # noqa: N802
                if not self._autorise():
                    self._refuse()
                    return
                chemin = urlparse(self.path).path
                if chemin == "/cadre.jpg":
                    with coloriage._verrou:
                        corps = coloriage._jpeg
                    if not corps:
                        self.send_response(204)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(corps)))
                    self.end_headers()
                    self.wfile.write(corps)
                    return
                corps = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def do_POST(self):  # noqa: N802
                if not self._autorise():
                    self._refuse()
                    return
                chemin = urlparse(self.path).path
                if chemin == "/efface":
                    coloriage.efface()
                elif chemin == "/touche":
                    taille = int(self.headers.get("Content-Length") or 0)
                    try:
                        recu = json.loads(self.rfile.read(taille) or b"{}")
                    except (ValueError, UnicodeError):
                        recu = {}
                    coloriage.pose(recu.get("x", -1), recu.get("y", -1),
                                   str(recu.get("couleur") or ""), time.time())
                self.send_response(204)
                self.end_headers()

        ThreadingHTTPServer.allow_reuse_address = True
        self._serveur = ThreadingHTTPServer(("0.0.0.0", port), Requete)
        self._fil = threading.Thread(target=self._serveur.serve_forever, daemon=True)
        self._fil.start()

    def ferme(self) -> None:
        if self._serveur is not None:
            self._serveur.shutdown()
            self._serveur.server_close()
            self._serveur = None
