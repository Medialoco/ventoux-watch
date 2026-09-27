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

## Ce qui reste à faire

- Faire remonter ces périodes sur le site. Un historique qui ne distingue pas
  « rien ne s'est passé » de « personne ne regardait » ment par omission.
- Vérifier que le veilleur du Pi ne souffre d'aucune de ces morts silencieuses
  une fois la machine en service.
