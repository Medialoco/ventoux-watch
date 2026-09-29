# Tout capter

Le but : **tout mouvement devant la caméra est détecté et interprété.** Pas
seulement les voitures et les piétons — les nuages, les ombres qui courent sur
la pente, la lumière des phares sur le bitume. Ce ne sont pas des parasites à
écarter : ce sont exactement les faux positifs des voitures et des cars, et
tant qu'ils n'ont pas de nom ils reviendront.

Trois choses en découlent. Une scène entièrement nommée devient un banc d'essai
honnête pour simuler des départs de feu, puisqu'on saura ce qu'un vrai nuage
fait dans cette image. Le taux de justesse devient mesurable au lieu d'être
supposé. Et un flux habillé des détections devient montrable.

## Où on en est, en chiffres

Sur les 418 entrées publiées, 143 ont été reconnues par le modèle lui-même,
25 nommées par une règle de rattrapage, 250 sont antérieures à la mesure.
Une seule des 54 relues par un humain était juste du premier coup.

En face, **7 607 taches ont été refusées en vingt-quatre heures**, et voici
sous quel motif :

| Motif | Nombre | Ce que c'est vraiment |
| --- | --- | --- |
| `none` | 2 949 | rien à dire : le fourre-tout |
| `sky_still` | 1 801 | le ciel qui bouge à peine — des nuages |
| `repeated_spot` | 532 | ça rebouge au même endroit |
| `against_the_ground` | 490 | trop grand pour le sol qu'il occupe |
| `unnamed_vehicle` | 424 | quelque chose a traversé, sans classe |
| `fog` | 338 | brume |
| `static` | 314 | pas assez de déplacement |
| `slope_still` | 186 | la pente qui frémit |
| `tarmac`, `island`, `landmark` | 111 | du décor qui prend la lumière |
| le reste | 462 | |

Le point à retenir : **ce ne sont pas des classes, ce sont des refus.**
`too_small` dit pourquoi on n'a pas voulu en parler, pas ce que c'était. Une
seule tache en vingt-quatre heures a reçu le nom « nuage ». Le travail consiste
à remplacer ce tableau de refus par un tableau de noms.

## Étape 0 — Savoir où on en est

Rien ne se règle avant d'être mesuré ; la dernière fois qu'un seuil a été posé
par raisonnement, il refusait de vrais panaches.

1. **Calibrer.** Relire des entrées tirées au sort, et pour chaque tranche de
   score du modèle, compter la part de justes. On ne publie que les tranches
   qui tiennent 95 %. Le seuil sort de la mesure, pas d'un chiffre rond — et il
   sera probablement différent par classe : les voitures et les piétons ne se
   lisent pas avec la même sûreté sur cette image.
   *Pourquoi ce n'est pas encore fait : les 54 relectures existantes sont
   celles qui clochaient. Elles diraient que tout est faux.*
2. **Rejouer le modèle d'aujourd'hui** sur les gros plans conservés. Ceux de
   l'historique portent la lecture des règles d'alors, qui ont changé.
   *Limite : 152 gros plans seulement, le reste n'a pas été gardé. La mesure
   propre se construit à partir de maintenant.*

## Étape 1 — Nommer le décor au lieu de le refuser

Une chose qui bouge et qui n'est pas un objet est presque toujours l'une de
ces trois-là : **une ombre, une lumière, ou une masse d'eau dans l'air.**
Chacune a une signature physique, comme le feu a la sienne.

### L'ombre et la lumière : la texture ne change pas

C'est le levier le plus rentable et il n'est pas utilisé. Une ombre qui passe,
ou la flaque des phares, **change la luminosité sans changer la texture** : le
muret reste le muret, ses pierres sont toujours là, simplement plus sombres ou
plus claires. Un objet, lui, masque ce qu'il y a derrière.

Mesurable de deux façons, l'une gratuite :

- `cv2.createBackgroundSubtractorMOG2` sait le faire et **c'est désactivé chez
  nous** (`detectShadows=False`, watcher/motion.py). L'activer rend un masque
  où l'ombre porte une valeur à part.
- Plus sûr et symétrique : sur la tache, comparer l'image au fond mémorisé. Si
  le rapport des deux est à peu près constant sur toute la tache, c'est un
  changement d'éclairage ; s'il varie, quelque chose est passé devant.

C'est exactement la faute du 29 septembre à 02:51, où le rectangle a atterri
sur la lumière des phares plutôt que sur la voiture.

### La scène OSM comme base d'interprétation

Cette couche existe déjà et elle porte plus qu'on ne s'en sert. `relief.json`
tient **162 bâtiments avec leur hauteur et leur empreinte en mètres**, 9 arbres
avec la leur, 67 bois, 275 tronçons de route, 5 mâts, un lampadaire relevé à
7 m, et un terrain de 126 × 126 mailles de 40 m sur deux kilomètres et demi.
`scene.json` en tire, pour chaque point de l'image, la surface, la distance et
l'échelle. C'est déjà ce qui permet de dire qu'une tache fait 5,8 m de large,
qu'elle est posée sur la chaussée, et qu'un piéton de 40 cm n'en est pas un.

Ce qui manque, c'est de s'en servir pour **prédire**. Trois usages, du plus
rentable au plus lointain.

**Les ombres portées sont calculables.** On sait où est le soleil à la seconde
près — `solar_azimuth` et `solar_elevation` sont écrits depuis le début. Avec
la hauteur des objets et le relief, on sait donc où chaque ombre tombe et
combien elle mesure. L'ombre du lampadaire du rond-point fait 15,4 m à 8 h
UTC, 7,4 m à midi et 27,6 m à 16 h.

Et surtout elle bouge à la vitesse du soleil, c'est-à-dire quinze degrés par
heure : la pointe de cette ombre de 27 m avance de **deux millimètres par
seconde**. Sur une piste de quatorze secondes, elle a parcouru trois
centimètres. Une ombre portée par une chose fixe est donc, pour nous,
immobile — et elle est à un endroit qu'on sait calculer d'avance. C'est ce qui
la sépare d'une ombre de nuage, qui file à la vitesse du vent.

*Réserve à connaître : 159 des 162 bâtiments portent une hauteur de 6 m, qui
est une valeur par défaut et non un relevé. La longueur des ombres de
bâtiments sera donc approximative ; leur direction, elle, est juste, et c'est
la direction qui explique un bord qui bouge.*

**L'occultation.** La scène dit ce qui est devant quoi. Une piste qui s'arrête
net derrière le chalet n'a pas disparu, elle est cachée — aujourd'hui la piste
se termine simplement, et la voiture qui ressort de l'autre côté devient un
second passage.

**Ce qui peut physiquement se trouver là.** Un véhicule est sur la chaussée et
mesure entre trois et douze mètres ; à 300 m un piéton fait quelques pixels et
une tache de trois pixels ne peut pas en être un. C'est en partie fait
(`drivable_near`, `metres_across`), pas systématique.

### Le nuage et la brume : le pied monte autant que le haut

Déjà mesuré pour le feu, et transposable tel quel. Un panache est ancré au sol
qui brûle ; un nuage se translate en bloc. On a `rise_ms`, `foot_climb`,
`drift`. Il manque juste de s'en servir pour **nommer** le nuage au lieu de
simplement refuser le feu.

### Le reste

La végétation dans le vent (oscille sans avancer), les oiseaux (petits,
rapides, en l'air), la pluie et la neige sur l'objectif (partout à la fois),
le grain du capteur la nuit. Chacun aura sa mesure, écrite après un cas réel
et pas avant.

**Sortie mesurable de l'étape :** la part des taches qui finissent sans nom.
Aujourd'hui c'est l'écrasante majorité. L'objectif est qu'elle devienne rare,
et que « je ne sais pas » redevienne une information au lieu d'être la règle.

## Étape 2 — Tout mouvement porte une interprétation

Chaque piste se termine par un nom pris dans une liste fermée — véhicule,
personne, deux-roues, animal, nuage, ombre, lumière, précipitation, bruit,
inconnu — avec sa sûreté. Ce qui est sûr à 95 % va sur le site. Le reste va
sur la seconde page, celle où on reprend les cas un par un, et chacun de ces
cas fait bouger une mesure ou un seuil.

Le fichier d'apprentissage est déjà en place : chaque verdict y écrit ce que la
veille avait dit, ce que c'était, et les mesures du moment.

## Étape 3 — Simuler des départs de feu sur une scène connue

C'est le vrai gain de l'étape 1, et c'est le raisonnement juste : on ne peut
pas savoir si un détecteur de fumée distingue un panache d'un nuage tant qu'on
ne sait pas reconnaître un nuage.

Le simulateur dessine déjà le panache en mètres via l'échelle du terrain. Une
fois les nuages nommés, on injecte un feu simulé dans des scènes réelles
choisies — ciel dégagé, nuages bas, brume du matin, nuit — et on mesure ce qui
passe et ce qui est confondu. C'est ce qui donnera une distance de détection
honnête plutôt qu'une distance mesurée un jour de beau temps.

## Étape 4 — Le direct habillé

Un flux YouTube où l'on voit les détections se poser sur l'image.

Techniquement, c'est un autre métier que la veille : la veille lit une image
par seconde, un direct doit ré-encoder vingt-cinq images par seconde en
permanence. Deux points de réalité à ne pas découvrir en route :

- **Le Raspberry Pi 5 n'a pas d'encodeur H.264 matériel.** Contrairement au
  Pi 4, il a perdu cet accélérateur. Un 1080p25 en x264 logiciel sur le Pi, en
  plus de la veille, n'est pas raisonnable ; 720p ou un encodage sur une autre
  machine le sont.
- Les boîtes doivent être posées sur le flux sans attendre la décision, qui
  prend plusieurs secondes — donc un léger différé, ou des boîtes qui
  apparaissent après coup.

À faire en dernier : un direct qui montre de mauvaises détections est pire que
pas de direct.

## Est-ce que ça a déjà été fait ?

Pas exactement, autant qu'on sache, et il faut être précis sur ce qui existe.

La détection de fumée sur réseaux de caméras fixes est un domaine actif et
industrialisé : **ALERTWildfire / ALERTCalifornia** exploite plus d'un millier
de caméras dans l'Ouest américain avec de la détection automatique, **HPWREN**
a produit la bibliothèque d'images **FIgLib** qui sert de référence à beaucoup
de travaux universitaires, et des sociétés comme **Pano AI** en ont fait un
produit. Tous cherchent la fumée.

Ce qui est moins courant, c'est de **nommer tout ce qui bouge**, nuages et
ombres compris, comme des classes à part entière plutôt que comme du bruit à
soustraire. La littérature sur la soustraction de fond traite les ombres
comme un artefact à supprimer, pas comme une observation à publier. L'intérêt
n'est pas la nouveauté pour elle-même : c'est que les faux positifs d'un
détecteur de feu sont précisément ces objets-là, et qu'on ne peut pas mesurer
ce qu'on ne nomme pas.

## Ce qui ne bouge pas

Les seuils restent physiques — des mètres, des mètres par seconde, des
rapports — pour que le modèle serve sur une autre webcam dont on connaîtra la
carte OSM. Aucun seuil ajusté au cadrage de celle-ci.
