# Incidents

Ce que le veilleur a raté, quand, et pourquoi. Deux choses sont notées ici :
les **pannes**, avec leur cause et le correctif, et les **périodes de non
surveillance**, c'est-à-dire les moments où la montagne n'était regardée par
personne.

Le second point est le plus important. Un veilleur qui se trompe, on le
corrige ; un veilleur qui ne regarde pas ne se trompe jamais, et c'est
exactement ce qui le rend dangereux. Une webcam surveillée neuf heures sur
vingt-quatre n'est pas une webcam surveillée.

## Ce qui permet de le savoir

Trois traces, et aucune n'est complète :

- `data/watch.log` garde la ligne « Carte de la scène » à chaque démarrage.
  Comme le veilleur refuse de démarrer si un autre tient déjà le verrou
  (`data/watch.lock`), **chaque démarrage réussi prouve qu'aucun veilleur ne
  tournait à cet instant**.
- `data/battement` porte la date de la dernière image traitée. Il donne
  l'heure de mort à la seconde, mais il est écrasé à chaque relance : on ne
  connaît que la dernière.
- `data/events.json` donne l'heure du dernier événement publié, ce qui est un
  minorant grossier — une heure sans rien publier peut être une heure sans
  rien à voir.

Depuis le 27 septembre au soir, le veilleur tient lui-même
`data/interruptions.jsonl` : une ligne par période, avec son début, sa fin et
sa durée. L'écart entre deux battements est par construction du temps sans
surveillance, qu'il vienne d'un veilleur arrêté ou d'un flux qui s'est tu, et
c'est le seul instant où ce chiffre est encore connaissable — une image plus
tard, le battement est écrasé. Le fichier est publié avec l'historique qu'il
explique. Les interruptions de moins de trente secondes ne sont pas notées :
c'est une relance prise au vol, pas un trou.

Le tableau ci-dessous, lui, a été reconstitué après coup et le restera : les
périodes d'avant le 27 septembre sont définitivement perdues.

`data/sky.jsonl` ressemble à un journal de fonctionnement — une ligne par
minute — mais n'en est pas un : l'archive n'écrit que lorsqu'il y a un avion
dans le cadre. Ses trous mesurent le trafic aérien, pas la surveillance. Elle
ne doit pas servir à ce calcul.

## Périodes de non surveillance

Heures de Paris, comme sur le site. Ce tableau s'arrête au 27 septembre au
soir ; après cette date, `data/interruptions.jsonl` fait foi (heures UTC).

| Début | Fin | Durée | Cause |
| --- | --- | --- | --- |
| avant le 27/09 | — | inconnu | non enregistré, non reconstituable |
| 27/09 ~16:10 | 16:14:58 | ~5 min | veille tuée avec son terminal |
| 27/09 ~16:16 | 16:25:37 | ~10 min | veille tuée avec son terminal |
| 27/09 ~16:27 | 16:53:29 | ~26 min | veille tuée avec son terminal |
| 27/09 ~16:54 | 18:12:24 | ~78 min | veille tuée avec son terminal |
| 27/09 18:12:40 | 18:59:37 | 47 min | veille tuée avec son terminal |
| 27/09 ~19:00 | 19:11:56 | ~12 min | veille tuée avec son terminal |
| 27/09 19:13:46 | 20:13:47 | 60 min | veille tuée avec son terminal |

Entre 16:09 et 20:13 le 27 septembre, la montagne n'a donc été regardée que
par bouffées de quelques dizaines de secondes, séparées par des heures de
rien. Le dernier événement publié de cette tranche est la voiture de
**16:25:59**, et c'est l'usager qui a signalé le silence, pas la machine.

Les dates précédées de « ~ » sont encadrées, pas mesurées : on sait qu'aucun
veilleur ne tournait à l'heure du démarrage suivant, et l'heure de mort exacte
n'a pas été conservée.

Le même mode de lancement était utilisé les jours précédents. Les mêmes
interruptions s'y sont donc très probablement produites, sans qu'on puisse
aujourd'hui dire lesquelles ni combien de temps.

## Les pannes du 29 septembre

### Trente-huit minutes sans regarder, service au vert

De 07:04 à 07:48 UTC, premier jour du Raspberry. Le service était actif depuis
07:09 et n'a traité sa première image qu'à 07:48 : pendant trente-huit
minutes, `systemctl status` affichait un veilleur en bonne santé qui ne
regardait rien. C'est très exactement le cas vicieux pour lequel le battement
de cœur avait été écrit.

Il n'a pas mordu. Non parce qu'il était mal conçu — sa logique, éprouvée
depuis sur un faux battement de dix minutes, relance bien — mais parce qu'il
n'avait **jamais été armé** : `scripts/pi_install.sh` faisait
`systemctl enable ventoux-battement.timer` sans `--now`. La minuterie était
donc inscrite pour le prochain démarrage, et le Raspberry n'avait pas
redémarré. Neuf heures durant, `systemctl is-enabled` répondait `enabled` et
`is-active` répondait `inactive`, sans que rien ne signale l'écart.

La leçon dépasse le `--now` manquant. **Un garde-fou installé n'est pas un
garde-fou armé**, et l'installation rendait compte de ce qu'elle avait écrit
sur le disque, pas de ce qui protégeait la machine à la fin. Elle affiche
désormais l'état réel des deux filets — battement et chien de garde matériel —
et le dit en toutes lettres quand l'un dort. Sur cent machines, cette
distinction est la différence entre un parc surveillé et un parc qu'on croit
surveillé.

Le chien de garde matériel, lui, était bien armé : `/dev/watchdog` présent,
`RuntimeWatchdogSec=15` pris en compte par systemd.

### Deux veilleurs sur la même webcam

Pendant un quart d'heure, le Mac et le Raspberry ont observé la même caméra et
publié dans le même dépôt. Le passage de 06:33 au rond-point existe donc deux
fois, vu par l'un à 06:33:31 et par l'autre à 06:33:33.

Sans conséquence cette fois — les doublons du Mac ont été écartés, le dépôt
n'a rien perdu — mais le verrou `data/watch.lock` ne protège que d'un second
veilleur *sur la même machine*. Il ne dit rien de deux machines. Le compteur
qui numérote les événements est lui aussi local : les deux veilleurs
repartaient chacun de 1, et rien n'empêche deux identifiants de coïncider à la
seconde près. À cent caméras, il faudra que l'identité d'un veilleur fasse
partie de ce qu'il publie.

## Les pannes du 28 septembre

### Un tracteur publié comme départ de feu

14:02, sur la prairie. Une cabine grise sur de l'herbe verte satisfait le test
de fumée — pâle, grise, et `bleu − rouge < 25`, donc « ce n'est pas le ciel » —
la tache est montée de 2,8 % de l'image et a triplé de surface. Le modèle n'a
rien vu du tout pour la contredire : à sept mètres de large et à cette
distance, l'engin fait une vingtaine de pixels.

Ce qu'il ne peut pas contrefaire, c'est la poussée d'Archimède. La fumée d'un
feu qui vient de prendre est portée par sa propre chaleur et monte à plusieurs
mètres par seconde ; rien d'autre sur cette montagne ne monte. Le haut du
tracteur montait à **0,55 m/s**, les onze relevés faits sur trois panaches
simulés donnent entre **2,21 et 3,34 m/s**. Seuil `FIRE_CLIMB_MS` à 1 m/s,
demandé aux seules masses froides, et **ignoré quand il n'est pas mesurable** :
sans relevé du terrain il n'y a pas de mètre, et un feu qu'on ne sait pas
mesurer doit pouvoir alerter quand même.

#### Ce qui a été essayé avant, et pourquoi c'était faux

D'abord le déplacement du **pied** de la tache : un foyer ne traverse pas le
terrain, il grandit sur place. L'idée était juste et la mesure ne l'a pas
suivie. Un camion réel passé le matin même dérivait de 0,063 de sa largeur par
seconde, et un vrai panache dessiné à sa taille réelle montait à 0,082 : les
deux se recouvrent. Pire, le garde-fou refusait des panaches authentiques une
seconde sur trois.

Puis la **droiture** du pied — distance parcourue sur terrain couvert, l'idée
étant qu'un engin marche en ligne et qu'un pied déchiqueté piétine. Échec aussi :
un panache qui penche dans un vent régulier marque jusqu'à 0,94, aussi droit
que n'importe quoi qui roule.

Les deux mesures ont été retirées de la décision. La dérive reste **inscrite**
dans chaque événement, sans juger : le prochain cas de ce genre se diagnostique
sur ce qui a été écrit, pas sur des suppositions.

### Un cycliste publié comme « Voiture orange »

14:52, au rond-point. Le modèle a lu « car » à 0,30 de confiance — bien en
dessous du seuil habituel — sur une boîte de neuf pixels sur quinze. La
branche qui rattrape les lectures faibles a alors demandé au sol de trancher :
3,5 m sur 2,0, plus large que haut, c'est-à-dire en forme de voiture. Publié.

Le sol avait raison sur l'empreinte : un vélo avec une remorque et son cycliste
occupent bien cette place. C'est l'assemblage qui était faux. **La boîte du
modèle couvrait 3,9 % de ce qui avait bougé.** Un mot dit sur un vingt-cinquième
d'une chose ne dit rien de la chose.

Correctif : dans cette branche — et dans elle seule, car elle est déjà une
exception — la lecture doit couvrir au moins un cinquième de la tache pour que
son mot vaille pour l'ensemble (`NAMED_SHARE`). Un cinquième laisse la place à
une tache gonflée par l'ombre, par le halo des phares sur la chaussée, ou par
une deuxième chose qui a bougé à côté.

La mesure de recouvrement est désormais inscrite dans chaque événement, à côté
de ce que le modèle a cru voir : `car 0.30 sur 4 %` se lit d'un coup d'œil, là
où il fallait jusqu'ici reconstituer le calcul à la main.

Deux mesures voisines existent maintenant et répondent à des questions
opposées. `_overlap` demande si le modèle regardait la chose qui bougeait, et
décide où va le rectangle. `_covers` demande s'il en regardait la totalité, et
décide si son mot vaut pour l'ensemble.

### Le simulateur dessinait un panache qui n'était pas à l'échelle

Trouvé en vérifiant le correctif ci-dessus, et plus grave que lui. Le panache
de `watcher/simulate.py` était dessiné en **parts d'image** et non en mètres.
Sa taille réelle dépendait donc de l'endroit où on le posait : au même nombre
de pixels, un foyer lointain représentait un incendie énorme et un foyer proche
un feu de camp. Les quatre panaches essayés faisaient entre 13 et 21 m de large
dès leur première seconde et jusqu'à 60 m à la sixième — et étaient tous
refusés comme « Nuage sur la pente » par le plafond `FIRE_WIDEST_M = 30` posé
la veille.

Le plafond n'était donc pas en cause : l'étalon l'était. Le panache est
maintenant dessiné en mètres, par `SceneMap.share_per_metre()`, avec des
constantes physiques — 2 m/s de montée, 0,45 m/s d'élargissement, 1,2 m/s de
vent, et un front de flamme qui progresse au sol à 0,25 m/s, dix fois moins
vite que la colonne ne s'élève.

Le plancher de quatre pixels du cœur de flamme est tombé à un : une flamme qui
couvre moins d'un pixel à cette distance en couvre moins d'un, et la rembourrer
revenait à faire passer les foyers lointains en les dessinant plus près qu'ils
ne sont.

### La portée réelle, enfin mesurée

Avec le panache à l'échelle, sur une image figée, un départ de feu est nommé :

| Distance | De jour | De nuit |
| --- | --- | --- |
| 106 m | 6e seconde | 6e seconde |
| 230 m | 7e seconde | 7e seconde |
| 390 m | 10e seconde | 12e seconde |
| 544 m | 10e seconde | 10e seconde |
| 830 m | 17e seconde | 18e seconde |

Le mystère du foyer à 578 m « jamais vu » était donc le simulateur, pas le
veilleur. Un seul emplacement manque de jour, à 198 m : il tombe dans la zone
route, où le feu n'est pas cherché du tout puisqu'un foyer se juge sur du
combustible. Un véhicule qui brûle sur la chaussée n'est aujourd'hui pas
couvert, et c'est une question ouverte, pas un réglage.

**Le simulateur n'est pas reproductible par défaut** : `--frame live` tire une
image du direct à chaque lancement, donc deux séries ne se comparent pas. Toute
mesure de seuil doit passer par `--frame` sur une photo figée. Deux conclusions
de la journée ont d'abord été tirées sans cela et étaient fausses.

## Les pannes du 27 septembre

### La veille mourait avec le terminal qui l'avait lancée

**La panne principale, et celle qui a coûté les heures ci-dessus.** La veille
était lancée en arrière-plan depuis un terminal. `nohup` ne protège que du
signal de raccrochage : quand la session du shell est terminée, tout son
groupe de processus part avec elle. La durée de vie a varié de trente et une
secondes à une demi-heure, selon le moment où la session était récupérée — ce
qui donnait l'impression d'une panne intermittente et sans cause.

Rien n'apparaissait dans le journal : une mort par signal ne laisse ni trace
d'erreur ni rapport de plantage.

Deux choses m'ont retardé sur ce diagnostic, et elles valent d'être notées :

- **Le fichier de verrou gardait le numéro du processus mort.** J'ai lu ce
  numéro et conclu que le processus vivait. Un verrou n'est pas une preuve de
  vie, c'est un numéro écrit sur un fichier ; la seule vérification valable
  est de demander au système si ce numéro existe encore.
- J'ai d'abord attribué la panne à une lecture bloquante (ci-dessous), qui
  était un vrai défaut mais pas celui-là.

Correctif : `scripts/mac_veille.sh`, qui détache la veille dans sa propre
session (`setsid`) avant de la lancer. Elle est alors rattachée à `launchd`,
plus au terminal. Sur le Raspberry, systemd rend le problème sans objet.

### Une lecture de flux sans délai d'attente

Défaut réel, trouvé en cherchant le précédent, corrigé au passage. `_frames()`
lisait la sortie de `ffmpeg` sans limite de temps. Quand le flux se tarit,
`ffmpeg` ne meurt pas — son option `-reconnect` le maintient précisément en
vie pendant qu'il tente de se raccrocher — et la lecture attend alors
indéfiniment : pas d'exception, pas de ligne de journal, pas de sortie.

Correctif : `select` avec `STREAM_SILENCE_S = 30`. Un flux qui donne une image
par seconde et se tait trente secondes est un flux à rouvrir.

### Le garde-fou macOS refusé par le système

Un agent `launchd` avait été écrit pour relancer la veille depuis le Mac. Il
échouait avec « Operation not permitted » : la protection de confidentialité
de macOS interdit à un agent de lire dans `~/Desktop` sans autorisation
explicite. Il a été retiré plutôt que laissé en place — un garde-fou qui ne
peut pas fonctionner est pire qu'aucun, il rassure à tort.

### Trois faux départs de feu

Nuages et brouillard résiduel de la nuit nommés « Fire starting » à 10:09:49,
10:40:03 et 11:33:59. Deux mesures manquaient : un feu ne prend pas dans le
ciel, et un panache reste accroché au sol quand un nuage se déplace en bloc.
Ajout de `foot_climb` (déplacement signé du pied de la tache), du refus de
tout feu en zone `sky`, et d'un plafond de largeur `FIRE_WIDEST_M = 30` qui ne
s'applique qu'aux masses froides — un vrai incendie de 60 m de large doit
continuer d'alerter. Les trois événements ont été retirés de l'historique.

### Le rectangle sur le mauvais sujet

Deux fois. À 16:06:35, la voiture nommée n'était pas encadrée et le groupe de
piétons l'était : les boîtes du modèle étaient jetées à la construction, le
rectangle retombait sur la tache de mouvement. À 16:25:59, le rectangle
tombait sur une voiture à l'arrêt : la boîte la plus sûre n'est pas celle qui
a bougé. Correctif : conserver les boîtes du modèle, puis les filtrer par
recouvrement avec le mouvement (`BOX_OVERLAP = 0.33`).

### Le Raspberry Pi qui démarre puis s'éteint

Diode verte cinq secondes, puis rouge seule. Le Pi 5 réclame 5 V / 5 A. Un
chargeur d'ordinateur portable annonce sa puissance à 20 V et ne fournit
souvent que 2 A en 5 V : la carte démarre et s'effondre. Alimentation 27 W
commandée. Détaillé dans [infra.md](infra.md).

### Ce que les corrections deviennent

Jusqu'au 28 septembre, corriger une lecture voulait dire modifier l'historique
et écrire pourquoi dans un commentaire de `scripts/fix_history.py`. Un verdict
rendu depuis le site, lui, ne déplaçait que deux compteurs dans
`data/learning.json` : combien de fois nous avons raison, combien de fois
tort, et rien sur le pourquoi.

Désormais chaque verdict écrit une ligne dans `data/reviewed.jsonl` : ce que la
veille avait dit, ce que c'était, la zone, la photo, et les mesures du moment
— largeur au sol, hauteur, vitesse de montée, ce que le modèle a lu. C'est la
seule matière qui permette de régler un seuil sur des faits plutôt que sur un
cas.

Les 87 corrections déjà rendues y ont été repassées par
`scripts/backfill_reviews.py`, qui retrouve dans git l'étiquette d'origine —
celle que la correction avait écrasée. Ce que le corpus dit :

| La veille a dit | C'était | Nombre |
| --- | --- | --- |
| Piéton | une voiture, un vélo, une moto, un camion | 33 |
| Départ de feu ou incendie | un nuage, du brouillard, un lampadaire | 13 |
| un avion nommé | un nuage sur la crête | 9 |
| Piéton | la statue, les pierres de l'îlot, un halo | 9 |

`scripts/replay_reviews.py` repose la question au modèle d'aujourd'hui sur le
gros plan conservé. Sur les rejets il se tait quinze fois sur seize : les faux
feux ne venaient pas de lui mais de nos règles. Sur les voitures mal nommées
il ne rend rien du tout — le même silence que les vingt-six passages du 28 au
soir.

Seules 20 des 87 corrections ont encore un gros plan : il n'était gardé que
pour les véhicules longs. Il l'est maintenant pour tout ce qui est publié,
trois mégaoctets par jour contre cinquante pour les vignettes.

## Ce qui reste à faire

- Décider si un véhicule qui brûle sur la chaussée doit alerter : aujourd'hui
  le feu n'est cherché que sur du combustible, donc la route en est exclue.
- Faire remonter ces périodes sur le site. Un historique qui ne distingue pas
  « rien ne s'est passé » de « personne ne regardait » ment par omission.
- Vérifier que le veilleur du Pi ne souffre d'aucune de ces morts silencieuses
  une fois la machine en service.
