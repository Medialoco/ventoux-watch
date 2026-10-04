# Ce qui est dessiné ailleurs

Presque tout ce que le flux dessine est tracé au trait dans `watcher/stream.py`
— le soleil, les pantins, le tapis, l'éléphant. Ce dossier est pour le reste :
les dessins qui existaient déjà et qu'on reprend tels quels.

## sous-marin.svg

Le sous-marin jaune de <https://benoit-prieur.fr/>, repris de
`images/ui/submarine.svg`. C'est le dessin de l'auteur de ce dépôt, pris chez
lui et non ailleurs ; il n'y a pas de question de droits à se poser, et c'est
la raison pour laquelle c'est celui-là.

## sous-marin.png

Le même, rasterisé à cinq fois sa taille puis rogné sur ses pixels opaques.

La rasterisation se fait ici, pas sur le Raspberry Pi : rendre du SVG demande
Cairo et ses dépendances, et la machine qui diffuse n'a pas à les porter pour
un dessin qui ne change jamais. Le PNG est donc dans le dépôt, et le SVG à
côté pour qu'on sache d'où il vient et qu'on puisse le refaire :

    scripts/rasterise.sh

Rogné, parce qu'un SVG rendu garde ses marges et qu'elles décalent le dessin
par rapport au point où le code croit le poser. Rogné une fois pour toutes
vaut mieux qu'un décalage à corriger à la main.

## trampoline.jpg

Le trampoline élastique du Mont Serein, photographié le 28 juin 2026
par Marianne Casamance. Wikimedia Commons, CC BY-SA 3.0.

https://commons.wikimedia.org/wiki/File:Acivit%C3%A9s_estavales_(88728).jpg

Recadré sur le V jaune et le tapis. À l'écran il est teinté comme la
photo du Raspberry : c'est le disque français, en face du disque de
Los Angeles.

## dogmazic.svg

Le chien orange de Dogmazic, pris sur play.dogmazic.net — c'est leur
favicon, le même dessin que Wikimedia Commons publie en CC BY-SA 4.0.

https://commons.wikimedia.org/wiki/File:Dogmazic.png
https://play.dogmazic.net/

Association Musique Libre !, 2015. On le montre pour les remercier :
c'est de leur archive que vient presque toute la musique du flux.

## dogmazic.png

Le même, rasterisé à cinq fois sa taille puis rogné sur ses pixels
opaques, comme le sous-marin. `scripts/rasterise.sh`.
