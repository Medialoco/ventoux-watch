#!/bin/sh
# Refait les PNG de assets/ à partir des SVG.
#
# À lancer sur une machine de travail, pas sur le Raspberry Pi : il faut
# rsvg-convert, et le Pi n'a aucune raison de porter Cairo pour des dessins
# qui ne changent jamais. Le résultat est versionné.
set -eu
cd "$(dirname "$0")/.."

command -v rsvg-convert >/dev/null || {
    echo "Il faut rsvg-convert (brew install librsvg)." >&2
    exit 1
}

# Cinq fois la taille du viewBox : le sous-marin passe à cent soixante pixels
# de large à l'antenne, et on veut pouvoir le grossir sans qu'il bave.
rsvg-convert -w 1100 -h 600 -f png -o /tmp/sous-marin-brut.png assets/sous-marin.svg

# Le chien orange de Dogmazic. Le SVG officiel fait cent cinquante-huit
# pixels ; à l'antenne le disque en fait trois cents. Cinq fois, comme
# l'autre, pour qu'on puisse le poser sans qu'il bave.
rsvg-convert -w 790 -h 790 -f png -o /tmp/dogmazic-brut.png assets/dogmazic.svg

PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"
"$PYTHON" - <<'PY'
import cv2
import numpy as np

brut = cv2.imread("/tmp/sous-marin-brut.png", cv2.IMREAD_UNCHANGED)
# On rogne sur les pixels franchement opaques : le seuil écarte le voile
# d'anticrénelage qui entoure le dessin et qui, sinon, compterait comme de la
# matière et remettrait les marges qu'on essaie d'enlever.
ys, xs = np.nonzero(brut[:, :, 3] > 8)
cv2.imwrite("assets/sous-marin.png",
            brut[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
print("assets/sous-marin.png", cv2.imread("assets/sous-marin.png",
                                          cv2.IMREAD_UNCHANGED).shape)

brut = cv2.imread("/tmp/dogmazic-brut.png", cv2.IMREAD_UNCHANGED)
ys, xs = np.nonzero(brut[:, :, 3] > 8)
cv2.imwrite("assets/dogmazic.png",
            brut[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
print("assets/dogmazic.png", cv2.imread("assets/dogmazic.png",
                                       cv2.IMREAD_UNCHANGED).shape)
PY
