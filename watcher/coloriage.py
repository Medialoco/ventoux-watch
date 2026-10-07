"""Le coloriage du cadre, sur un calque, pour une diffusion plus tard.

La page montre le cadre, et le crayon vit sur un calque posé dessus. Le trait
suit la souris tant que le bouton est enfoncé, comme dans Paint. Il n'est pas
recopié dans l'image : la recopier le cassait en segments à chaque
rafraîchissement. YouTube n'en reçoit aucune. Le geste est noté pour être
rediffusé plus tard, dans le temps, et non posé d'un coup.

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
  #scene img { position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: contain; }
  #calque { position: absolute; touch-action: none; cursor: crosshair; }
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
  <canvas id="calque"></canvas>
</div>
<p class="note">Plus tard. Pas sur le direct.</p>
<div class="barre" id="barre"></div>
<script>
const jeton = new URLSearchParams(location.search).get("j") || "";
const couleurs = COULEURS_JSON;
const TRAIT = TRAIT_JSON;
let couleur = couleurs[0][0];
let css = couleurs[0][1];
let file = [];
const img = document.getElementById("cadre");
const calque = document.getElementById("calque");
const scene = document.getElementById("scene");
const barre = document.getElementById("barre");
let traits = [];
let courant = null;
let dessin = false;
let coupure = true;
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
  traits = [];
  courant = null;
  dessin = false;
  coupure = true;
  file = [];
  const ctx = calque.getContext("2d");
  ctx.clearRect(0, 0, calque.width, calque.height);
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
function place() {
  const b = boite();
  const s = scene.getBoundingClientRect();
  if (!b.dw || !b.dh) return;
  calque.style.left = (b.ox - s.left) + "px";
  calque.style.top = (b.oy - s.top) + "px";
  calque.style.width = b.dw + "px";
  calque.style.height = b.dh + "px";
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(b.dw * dpr));
  const h = Math.max(1, Math.round(b.dh * dpr));
  if (Math.abs(calque.width - w) < 2 && Math.abs(calque.height - h) < 2) return;
  if (dessin) return;
  calque.width = w;
  calque.height = h;
  repeint();
}
function sur(ev) {
  const r = calque.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  const x = (ev.clientX - r.left) / r.width;
  const y = (ev.clientY - r.top) / r.height;
  if (x < 0 || y < 0 || x > 1 || y > 1) return null;
  return {x, y};
}
function epaisseur() {
  return Math.max(1, Math.round(TRAIT * calque.width / 1600));
}
function repeint() {
  const ctx = calque.getContext("2d");
  ctx.clearRect(0, 0, calque.width, calque.height);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.lineWidth = epaisseur();
  traits.forEach((trait) => {
    if (!trait.points.length) return;
    ctx.strokeStyle = trait.css;
    ctx.fillStyle = trait.css;
    ctx.beginPath();
    trait.points.forEach((p, i) => {
      const x = p.x * (calque.width - 1);
      const y = p.y * (calque.height - 1);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    const a = trait.points[0];
    ctx.beginPath();
    ctx.arc(a.x * (calque.width - 1), a.y * (calque.height - 1), epaisseur() / 2, 0, Math.PI * 2);
    ctx.fill();
  });
}
function segment(de, vers, teinte) {
  const ctx = calque.getContext("2d");
  const ep = epaisseur();
  const X = (p) => p.x * (calque.width - 1);
  const Y = (p) => p.y * (calque.height - 1);
  ctx.strokeStyle = teinte;
  ctx.fillStyle = teinte;
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
function pose(ev) {
  const p = sur(ev);
  if (!p) { coupure = true; return; }
  const avant = courant && courant.points.length ? courant.points[courant.points.length - 1] : null;
  const relie = !coupure && avant;
  if (relie) {
    const r = calque.getBoundingClientRect();
    const dx = (p.x - avant.x) * r.width;
    const dy = (p.y - avant.y) * r.height;
    if (dx * dx + dy * dy < 0.6) return;
  }
  coupure = false;
  courant.points.push(p);
  file.push({x: p.x, y: p.y, suite: !!relie});
  segment(relie ? avant : null, p, courant.css);
}
let pompe = Promise.resolve();
function vide() {
  if (!file.length) return;
  const points = file;
  file = [];
  pompe = pompe.then(() => fetch("/touche?j=" + encodeURIComponent(jeton), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({couleur, points}),
  })).catch(() => {});
}
calque.addEventListener("pointerdown", (ev) => {
  if (ev.button !== 0) return;
  ev.preventDefault();
  dessin = true;
  coupure = true;
  courant = {css, points: []};
  traits.push(courant);
  pose(ev);
}, {passive: false});
window.addEventListener("pointermove", (ev) => {
  if (!dessin) return;
  if ((ev.buttons & 1) === 0) return;
  ev.preventDefault();
  pose(ev);
}, {passive: false});
function leve() {
  if (!dessin) return;
  dessin = false;
  courant = null;
  vide();
  place();
}
window.addEventListener("pointerup", leve);
window.addEventListener("pointercancel", (ev) => {
  if ((ev.buttons & 1) !== 0) return;
  leve();
});
setInterval(vide, 30);
place();
setInterval(place, 400);
window.addEventListener("resize", place);
img.addEventListener("load", place);
function rafraichit() {
  if (img.dataset.chargement === "1") return;
  img.dataset.chargement = "1";
  const url = "/cadre.jpg?j=" + encodeURIComponent(jeton) + "&t=" + Date.now();
  fetch(url).then((reponse) => reponse.status === 200 ? reponse.blob() : null).then((blob) => {
    img.dataset.chargement = "0";
    if (!blob) return;
    const objet = URL.createObjectURL(blob);
    const ancien = img.dataset.objet || "";
    img.onload = () => { if (ancien) URL.revokeObjectURL(ancien); place(); };
    img.dataset.objet = objet;
    img.src = objet;
  }).catch(() => { img.dataset.chargement = "0"; });
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
