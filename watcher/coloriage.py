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

# Épaisseur du trait, à la largeur de référence. Fin : un stylet, ou la souris
# bouton enfoncé. Encore lisible une fois le cadre encodé.
TRAIT = 4
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
  #scene { position: relative; flex: 1; min-height: 0; touch-action: none; }
  #scene img, #scene canvas { position: absolute; inset: 0; width: 100%; height: 100%;
    touch-action: none; }
  #scene img { object-fit: contain; }
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
<div id="scene">
  <img id="cadre" alt="">
  <canvas id="encre"></canvas>
</div>
<p class="note">Plus tard. Pas sur le direct.</p>
<div class="barre" id="barre"></div>
<script>
const jeton = new URLSearchParams(location.search).get("j") || "";
const couleurs = COULEURS_JSON;
const TRAIT = TRAIT_JSON;
let couleur = couleurs[0][0];
let css = couleurs[0][1];
let dernier = null;
let actif = null;
let file = [];
const img = document.getElementById("cadre");
const toile = document.getElementById("encre");
const barre = document.getElementById("barre");
couleurs.forEach(([nom, teinte]) => {
  const b = document.createElement("button");
  b.style.background = teinte;
  b.title = nom;
  b.className = nom === couleur ? "on" : "";
  b.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    couleur = nom;
    css = teinte;
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
  file = [];
  dernier = null;
  const dpr = window.devicePixelRatio || 1;
  toile.width = Math.max(1, Math.round(toile.getBoundingClientRect().width * dpr));
  toile.height = Math.max(1, Math.round(toile.getBoundingClientRect().height * dpr));
});
barre.appendChild(efface);
function boite() {
  const r = img.getBoundingClientRect();
  const iw = img.naturalWidth || r.width;
  const ih = img.naturalHeight || r.height;
  const echelle = Math.min(r.width / iw, r.height / ih);
  const dw = iw * echelle, dh = ih * echelle;
  const ox = r.left + (r.width - dw) / 2;
  const oy = r.top + (r.height - dh) / 2;
  return {r, iw, dw, dh, ox, oy};
}
function point(ev) {
  const b = boite();
  if (!b.dw || !b.dh) return null;
  const x = (ev.clientX - b.ox) / b.dw;
  const y = (ev.clientY - b.oy) / b.dh;
  if (x < 0 || y < 0 || x > 1 || y > 1) return null;
  return {x, y};
}
function prepare() {
  const dpr = window.devicePixelRatio || 1;
  const r = toile.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width * dpr));
  const h = Math.max(1, Math.round(r.height * dpr));
  if (toile.width !== w || toile.height !== h) {
    toile.width = w;
    toile.height = h;
  }
  return dpr;
}
function encre(de, vers) {
  const b = boite();
  if (!b.dw || !b.dh) return;
  const dpr = prepare();
  const ctx = toile.getContext("2d");
  const ep = Math.max(1, Math.round(TRAIT * b.iw / 1600)) * (b.dw / b.iw) * dpr;
  const X = (p) => (b.ox - b.r.left + p.x * b.dw) * dpr;
  const Y = (p) => (b.oy - b.r.top + p.y * b.dh) * dpr;
  ctx.fillStyle = css;
  ctx.strokeStyle = css;
  ctx.lineWidth = ep;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (!de) {
    ctx.beginPath();
    ctx.arc(X(vers), Y(vers), ep / 2, 0, Math.PI * 2);
    ctx.fill();
    return;
  }
  ctx.beginPath();
  ctx.moveTo(X(de), Y(de));
  ctx.lineTo(X(vers), Y(vers));
  ctx.stroke();
}
function envoie(ev, suite) {
  const p = point(ev);
  if (!p) return;
  if (suite && dernier && Math.hypot(p.x - dernier.x, p.y - dernier.y) < 0.003) return;
  encre(suite ? dernier : null, p);
  dernier = p;
  file.push({x: p.x, y: p.y, suite: !!suite});
}
function vide() {
  if (!file.length) return;
  const points = file;
  file = [];
  fetch("/touche?j=" + encodeURIComponent(jeton), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({couleur, points}),
  });
}
function trace(ev, suite) {
  const lot = ev.getCoalescedEvents ? ev.getCoalescedEvents() : [ev];
  lot.forEach((un, i) => envoie(un, suite || i > 0));
}
toile.addEventListener("pointerdown", (ev) => {
  if (ev.pointerType === "mouse" && ev.button !== 0) return;
  ev.preventDefault();
  toile.setPointerCapture(ev.pointerId);
  actif = ev.pointerId;
  dernier = null;
  trace(ev, false);
}, {passive: false});
toile.addEventListener("pointermove", (ev) => {
  if (ev.pointerId !== actif) return;
  ev.preventDefault();
  trace(ev, true);
}, {passive: false});
function leve(ev) {
  if (ev.pointerId !== actif) return;
  actif = null;
  vide();
}
toile.addEventListener("pointerup", leve);
toile.addEventListener("pointercancel", leve);
setInterval(vide, 40);
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
).replace("TRAIT_JSON", str(TRAIT))


class Coloriage:
    """Les touches reçues depuis l'ouverture, dessinées quand leur heure arrive."""

    def __init__(self, journal: Path | None = None) -> None:
        self.journal = journal
        self._touches: list[tuple[float, float, float, tuple[int, int, int], int]] = []
        self._trait = 0
        self._verrou = threading.Lock()
        self._jpeg = b""
        self._apercu = 0.0
        self._jeton = ""
        self._serveur: ThreadingHTTPServer | None = None
        self._fil: threading.Thread | None = None

    def pose(self, x: float, y: float, nom: str, quand: float, suite: bool = False) -> bool:
        teinte = COULEURS.get(nom)
        if teinte is None:
            return False
        try:
            x = min(1.0, max(0.0, float(x)))
            y = min(1.0, max(0.0, float(y)))
        except (TypeError, ValueError):
            return False
        with self._verrou:
            if not suite or self._trait == 0:
                self._trait += 1
            trait = self._trait
            touche = (float(quand), x, y, teinte, trait)
            self._touches.append(touche)
        self._note({"t": touche[0], "x": x, "y": y, "couleur": nom, "trait": trait})
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
        epaisseur = max(1, int(round(TRAIT * largeur / 1600)))
        rayon = max(1, epaisseur // 2)
        precedent = None
        for _quand, x, y, teinte, trait in lot:
            px = int(x * (largeur - 1))
            py = int(y * (hauteur - 1))
            if precedent is not None and precedent[0] == trait:
                cv2.line(image, (precedent[1], precedent[2]), (px, py),
                         teinte, epaisseur, cv2.LINE_AA)
            cv2.circle(image, (px, py), rayon, teinte, -1, cv2.LINE_AA)
            precedent = (trait, px, py)

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
                self.send_header("Cache-Control", "no-store")
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
                    if taille > 65536:
                        self.send_response(413)
                        self.end_headers()
                        return
                    try:
                        recu = json.loads(self.rfile.read(taille) or b"{}")
                    except (ValueError, UnicodeError):
                        recu = {}
                    if not isinstance(recu, dict):
                        recu = {}
                    quand = time.time()
                    nom = str(recu.get("couleur") or "")
                    points = recu.get("points")
                    if isinstance(points, list):
                        for point in points[:400]:
                            if isinstance(point, dict):
                                coloriage.pose(point.get("x", -1), point.get("y", -1),
                                               nom, quand, suite=bool(point.get("suite")))
                    else:
                        coloriage.pose(recu.get("x", -1), recu.get("y", -1), nom, quand)
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
