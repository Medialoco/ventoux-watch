# Mont Serein

*[In English](README.en.md)*

#FREETECHNORADIO

Un Raspberry Pi 5, sur un bureau à Los Angeles, regarde la webcam du col du Mont Serein, à 1 389 m sur le mont Ventoux. Une image par seconde. OpenCV trouve ce qui a bougé, YOLO nomme la découpe, et le Pi reconstruit le cadre : la photographie, le rectangle, les encarts, la musique. La veille est le travail. Le flux est le spectacle.

La veille voit beaucoup de mouvement. Une classe publiée compte dès qu’elle est nommée. L’acclamation verte, un good catch, attend 0,60. Sous chaque encart, trois digits montrent le rapport du jour fois cent, et le compte brut en petit. Los Angeles est à gauche, Beaumont-du-Ventoux à droite. Une classe compte des deux côtés. Chaque côté revient à 000 à son minuit, et les deux minuits ne tombent pas à la même heure.

Veilleur **v0.6.6**.

Le direct est sur [YouTube](https://www.youtube.com/watch?v=OwLQpSJLs-I). Le site est [medialoco.github.io/ventoux-watch](https://medialoco.github.io/ventoux-watch/). Vingt façons dont l’image change y sont écrites, chacune d’après le code qui tourne.

![Mont Serein, de nuit : rond-point, route, pente et balise du sommet](docs/mont-serein-nuit.png)

*24 septembre 2026, 23 h 41, heure de Paris. La photo a été prise à 14 h 41 à Los Angeles.*

La musique est libre, jour et nuit, avec la licence à l’écran pour chaque morceau. Elle vient de [Dogmazic](https://play.dogmazic.net/), et la playlist du flux est [publique](https://play.dogmazic.net/playlist.php?action=show_playlist&playlist_id=4803). Quatorze heures, cent cinquante-huit morceaux. Quatre de ces heures sont l’album [Mont Serein 002](https://play.dogmazic.net/albums.php?action=show&album=11242), écrit pour ce projet par [thepriben](https://play.dogmazic.net/artists.php?action=show&artist=7208).

Les tailles se lisent en mètres, à partir de la pose de la caméra et d’un modèle de terrain. Au-dessus de 5,5 m ce n’est pas une voiture, quoi qu’en dise le réseau. En dessous de deux mètres ce n’est pas un bus. Quand la mesure ne tient pas, elle est jetée. Zéro veut dire qu’on ne sait pas.

C’est une caméra et une curiosité. Rien de ce qu’elle dit n’est une alerte, et rien de ce qu’elle dit n’est à prendre pour une consigne.

## Faire tourner

Sur le Mac :

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python -r requirements-export.txt
.venv/bin/python scripts/export_model.py
.venv/bin/python -m unittest discover -s tests -v
```

`models/yolo11s.onnx` part avec le code. Le Pi n’installe pas PyTorch.

Sur le Pi, une seule commande, rejouable :

```bash
ssh ventoux 'bash -s' < scripts/pi_install.sh
```

Les secrets ne sont pas dans le dépôt. `config/local.json` se porte à la main, une fois, et il reste ignoré par git. OpenSky et Drive sont facultatifs. Le matériel, la carte, le disque et le chien de garde sont dans [`infra.md`](infra.md). Les pannes sont dans [`incidents.md`](incidents.md). La suite est dans [`plan.md`](plan.md).
