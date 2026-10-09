# Mont Serein

*[In English](README.en.md)*

#FREETECHNORADIO

Un Raspberry Pi 5, sur un bureau à Los Angeles, regarde la webcam du col du Mont Serein, à 1 389 m sur le mont Ventoux. Une image par seconde. OpenCV trouve ce qui a bougé, YOLO nomme la découpe, et le Pi reconstruit le cadre : la photographie, le rectangle, les encarts, la musique. La veille est le travail. Le flux est le spectacle.

Trois modes, et chaque caméra est le relais de l’autre.

Le Mont Serein. La playlist est ouverte, le cadre est le col. Cannes attend.

Cannes. La playlist du Mont Serein est fermée (`#EXT-X-ENDLIST`, ou un dernier segment plus vieux que 120 s). Le cadre est le direct municipal du boulevard du Midi, vers les plages du Midi, ouvert à 60 s du bord. Un fil relit la playlist du Ventoux toutes les 60 s, hors des images. Dès qu’elle est de nouveau en direct, l’image suivante revient au col, sans relancer la sortie YouTube. Si l’entrée de Cannes s’arrête pendant que cette playlist est vivante, le cadre revient au col. Si les deux playlists sont fermées, la dernière image est tenue.

Les deux. Tant que le Mont Serein est là, Cannes entre pendant 90 s, d’abord 75 s après l’ouverture, puis 900 s après la fin. Une fois, Cannes prend la place du col : la boîte de droite devient Cannes, le compteur reste en bas à droite, le médaillon est l’hôtel Le Splendid. La fois d’après, une rangée : Los Angeles, Mont Serein, Beaumont, Cannes, et le cartouche de droite pour Cannes. Les boîtes gardent leur largeur, les deux images sont plus étroites, chaque image garde son cadre. Les rapports restent sur Los Angeles et Beaumont. Le décodeur de Cannes ne tourne que pendant qu’elle est à l’écran. Dans la rangée, #FREETECHNORADIO est sous chaque image, et le fil entre les deux côtés est omis. Si l’image de Cannes n’est pas arrivée, le col garde toute la fenêtre.

Cannes sert la sécurité en mer. Cette caméra n’a pas eu d’interruption depuis 2022. Le Mont Serein a eu deux interruptions longues cette semaine : le 6 octobre à partir de 08:49, heure de Paris (dernier segment 06:49:04 UTC), et le 8 octobre à partir de 09:16 (dernier segment 07:16:39 UTC), avec entre les deux des reprises qui n’ont pas tenu.

Le Mont Serein a une grille de distances tirée d’OpenStreetMap, depuis le nœud [6410397171](https://www.openstreetmap.org/node/6410397171). Cannes est le nœud [14255983894](https://www.openstreetmap.org/node/14255983894), en 43,5467593, 6,9754344, cap 190°, sur un poteau du boulevard du Midi. La hauteur n’est pas sur ce nœud, et aucune grille n’a été calée : rien n’a été apparié entre l’image et la carte. Le cadre est découpé en route (un bout, en bas à droite), trottoir, plage, mer et ciel. La mer et la plage ne vont pas à YOLO. Un changement sur plus de 35 % du cadre est écarté. L’ours, le tapis, le sous-marin, la piste, l’éléphant et les bâtiments sont pensés pour le rond-point, la crête et la bergerie. Ils sont appliqués tels quels sur le cadre de Cannes, aux mêmes places, y compris pendant que la playlist du Mont Serein est fermée. La teinte, le soleil dessiné, le lampadaire, le pixel, le gris et l’onde suivent la même règle sur une image de Cannes vivante. Au retour du col, le même dessin reprend sa place sur son image. La vue 3D de la page ouvre ce même nœud, à côté de celle du Mont Serein.

La veille voit beaucoup de mouvement. Le réseau n’est appelé que de temps en temps, et pas du tout la nuit quand la crête a disparu : le rectangle de mouvement reste, le nom serait brouillard. Une classe publiée compte dès qu’elle est nommée. L’acclamation verte, un good catch, attend 0,60. Sous chaque encart, trois digits montrent le rapport du jour fois cent, et le compte brut en petit. Los Angeles est à gauche, Beaumont-du-Ventoux à droite. Une classe compte des deux côtés. Chaque côté revient à 000 à son minuit, et les deux minuits ne tombent pas à la même heure.

Veilleur **v0.6.47**.

Le direct est sur [YouTube](https://www.youtube.com/watch?v=OwLQpSJLs-I). Le site est [medialoco.github.io/ventoux-watch](https://medialoco.github.io/ventoux-watch/). Les façons dont l’image change y sont écrites, chacune d’après le code qui tourne.

![Mont Serein, de nuit : rond-point, route, pente et balise du sommet](docs/mont-serein-nuit.png)

*24 septembre 2026, 23 h 41, heure de Paris. La photo a été prise à 14 h 41 à Los Angeles.*

La musique est libre, jour et nuit, avec la licence à l’écran pour chaque morceau. Elle vient de [Dogmazic](https://play.dogmazic.net/), et la playlist du flux est [publique](https://play.dogmazic.net/playlist.php?action=show_playlist&playlist_id=4803). Quatorze heures et treize minutes, cent cinquante-huit morceaux. Quatre heures en sont l’album [Mont Serein 002](https://play.dogmazic.net/albums.php?action=show&album=11242), écrit pour ce projet par [thepriben](https://play.dogmazic.net/artists.php?action=show&artist=7208).

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
