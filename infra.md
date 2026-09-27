# Infrastructure

Où tourne le veilleur, sur quoi il écrit, et comment il se relève tout seul.
Ce fichier décrit l'état réel au 27 septembre 2026, y compris ce qui n'est pas
encore fait. Les pannes et les périodes de non surveillance sont tenues à part,
dans [incidents.md](incidents.md).

## Où ça tourne

Aujourd'hui sur le Mac, en permanence, lancé à la main par
`./scripts/mac_veille.sh`. C'est provisoire et ça ne survit pas à une fermeture
de session.

Ce script existe pour une raison précise. Lancée depuis un terminal, même avec
`nohup`, la veille meurt avec lui : `nohup` ne protège que du raccrochage, et
le shell qui se termine emporte tout son groupe de processus. Le 27 septembre
elle s'est arrêtée trois fois ainsi, chaque fois quelques secondes après la
commande qui l'avait démarrée, sans une ligne de journal pour le dire — la
mesure la plus trompeuse de la journée, parce que le fichier de verrou gardait
le numéro d'un processus qui n'existait plus. Le script fait du veilleur le
chef de sa propre session, et plus personne ne l'emporte en partant.

Demain sur un **Raspberry Pi 5**, qui est la machine cible : elle consomme
quelques watts, ne fait que ça, et se remplace pour cent euros. Le but à terme
est d'en poser une par webcam, donc tout ce qui suit est écrit pour être rejoué
à l'identique sur la centième.

## Le Raspberry Pi

### Matériel

| Pièce | Référence | État |
|---|---|---|
| Carte | Raspberry Pi 5 | en main |
| Carte mémoire | SanDisk Ultra 128 Go microSD (`SDSQUJQ-128G-GZ6MA`) | gravée |
| Alimentation | iUniker 27 W GaN USB-C PD, 5,1 V / 5 A (`B0FHH9K47T`) | attendue le 28 |
| Disque externe | Samsung T7 Shield 1 To (`B09YHQ3YZ5`) | attendu le 29 |

L'alimentation n'est pas un détail. Le Pi 5 ne fonctionne qu'en 5 V et réclame
5 A. Un chargeur de portable de 65 W délivre sa puissance en 20 V et souvent
2 A seulement en 5 V : la carte démarre, tire son pic de courant au moment où
le noyau monte le système, passe sous le seuil et s'éteint en cinq secondes.
C'est ce qui est arrivé le 27 septembre. Sans bloc 5 A, le Pi 5 plafonne aussi
ses ports USB à 600 mA, ce qui ne suffit pas à démarrer un SSD alimenté par le
bus ; avec, la limite passe à 1,6 A.

### Système

Raspberry Pi OS **Lite 64 bits**, sans bureau. La machine ne sert qu'à faire
tourner le veilleur, et tout ce qui n'est pas installé est autant de mémoire,
de mises à jour et de surface d'attaque en moins.

La personnalisation passe par **cloud-init** sur les images récentes, et non
plus par `firstrun.sh` : les réglages de l'Imager atterrissent dans `user-data`,
`network-config` et `meta-data`, à la racine de la partition `bootfs`.

Quatre valeurs comptent, et trois d'entre elles étaient fausses à la première
gravure :

- `hostname: ventoux` — en minuscules, parce que le Mac se connecte à
  `ventoux.local`.
- `user: ventoux`, avec la clé publique du Mac dans `ssh_authorized_keys` et
  `ssh_pwauth: false`. Pas de mot de passe sur SSH.
- `sudo: ALL=(ALL) NOPASSWD:ALL`. L'Imager avait écrit `sudo: null`, ce qui
  aurait privé le compte de tout droit d'administration et rendu le script
  d'installation inopérant.
- `regulatory-domain: "FR"`, dans `network-config` **et** dans
  `cfg80211.ieee80211_regdom=` de `cmdline.txt`. L'Imager avait mis `US`. Sous
  domaine américain, les canaux 12 et 13 de la bande 2,4 GHz sont interdits, or
  les box françaises les utilisent couramment : le Pi ignore alors le réseau
  comme s'il n'existait pas.

### Accès

Le Mac se connecte par `ssh ventoux`, grâce à cette entrée dans
`~/.ssh/config` :

```
Host ventoux ventoux.local
  HostName ventoux.local
  User ventoux
  IdentityFile ~/.ssh/id_ed25519_ventoux
  IdentitiesOnly yes
```

La clé `~/.ssh/id_ed25519_ventoux` sert **uniquement** à cette machine, pour ne
pas mêler cet accès aux autres. Raspberry Pi Connect n'est pas activé : tant
que le Pi est sur le réseau local, SSH suffit, et chaque voie d'accès distante
supplémentaire est une porte de plus sur la clé de déploiement GitHub que la
machine détient.

## L'installation

Un seul script, rejouable sans rien casser — c'est la condition pour en équiper
cent, puis mille.

```bash
ssh ventoux 'bash -s' < scripts/pi_install.sh
```

Il fait, dans l'ordre : les paquets système (`git`, `ffmpeg`, `python3-venv`,
les bibliothèques réclamées par OpenCV) ; le fuseau `Europe/Paris`, parce que
les horodatages du site sont lus par un humain sur place ; le plafonnement du
journal système à 50 Mo, parce qu'un journal qui écrit en continu est la
première chose qui use une carte SD ; la création d'une **clé de déploiement**
propre au Pi, qu'il faut déclarer en écriture sur le dépôt GitHub — le script
s'arrête et l'affiche tant que ce n'est pas fait ; un clone superficiel du
dépôt dans `/opt/ventoux-watch`, l'historique complet pesant plus de 400 Mo
pour rien ; l'environnement Python ; et le service systemd.

Le modèle `models/yolo11n.onnx` voyage avec le code. Le Pi n'installe jamais
PyTorch : l'export du modèle se fait sur le Mac.

## Le stockage

Pour l'instant **tout est sur la carte SD**. C'est acceptable au démarrage et
ça ne l'est pas à long terme : une carte SD s'use à l'écriture, et le veilleur
écrit une vignette par événement plus un battement par seconde.

Le disque externe arrive lundi. Le script qui le raccorde existe déjà :

```bash
ssh ventoux 'bash -s' < scripts/pi_attach_disk.sh -- /dev/sda EFFACER
```

Il efface le disque, exige donc qu'on le nomme et qu'on confirme, et refuse
tout ce qui ressemble au support du système. Deux points méritent d'être
connus.

D'abord il monte le disque **directement sur `data/`**, et non par un lien
symbolique. `data/` est suivi par git ; un lien ferait voir à git la
disparition de deux mille fichiers d'un coup, alors qu'un point de montage lui
est invisible.

Ensuite il vérifie que la liaison USB utilise **UASP** et le signale sinon. Un
boîtier tombé en `usb-storage` divise le débit par trois environ et charge le
processeur. Le Crucial X9 en particulier demande
`usb-storage.quirks=0634:5605:u` sur Raspberry Pi ; le T7 Shield n'a pas ce
défaut, c'est pourquoi c'est lui qui a été choisi.

Le montage dans `fstab` se fait par UUID, avec `nofail` : un disque débranché
ne doit pas empêcher le Pi de démarrer, sinon on perd la machine et la webcam
avec. Le service porte `RequiresMountsFor` sur `data/`, pour qu'il attende le
disque plutôt que d'écrire sur la carte SD sous le point de montage.

## Se relever tout seul

Trois pannes différentes, trois parades, parce qu'aucune ne couvre les autres.

**Le processus meurt.** systemd le relance : `Restart=always`, `RestartSec=10`.
C'est le cas facile et le seul que la plupart des installations traitent.

**Le noyau se fige.** Le compteur matériel du BCM2712 n'est plus caressé et la
carte redémarre d'elle-même au bout de quinze secondes
(`dtparam=watchdog=on` dans `config.txt`, `RuntimeWatchdogSec=15` pour
systemd). C'est la seule parade à un gel complet, et sur une machine sans
clavier elle compte.

**Le veilleur tourne sans travailler.** C'est le cas vicieux : `ffmpeg` peut
attendre indéfiniment un flux qui a cessé de répondre. Le processus vit, ne
consomme rien, et ne regarde plus la montagne — ni systemd ni le chien de garde
matériel ne voient quoi que ce soit. Le veilleur écrit donc `data/battement` à
chaque image, soit une fois par seconde, et une minuterie systemd vérifie
toutes les deux minutes que ce fichier a moins de cinq minutes. Sinon elle
relance le service et l'inscrit au journal.

Après une coupure de courant, le Pi 5 redémarre seul dès que l'alimentation
revient, et le service est activé au démarrage.

## La publication

Le veilleur pousse `data/events.json`, `data/learning.json` et `data/thumbs/`
sur GitHub, qui reconstruit le site par GitHub Pages :
[medialoco.github.io/ventoux-watch](https://medialoco.github.io/ventoux-watch/).

Le rythme est à deux vitesses. Un **départ de feu part immédiatement** ; tout
le reste est groupé et publié au plus toutes les **quinze minutes**
(`publish_interval_s`). Un quart d'heure de retard sur un incendie enlèverait à
cette webcam la seule chose pour laquelle elle existe.

Le dépôt a été ramené de 363 Mio à 61 Mio le 27 septembre en réécrivant
l'historique : 1698 vignettes du 25 septembre avaient été stockées en
1920 × 1080 au lieu de 480 px, soit 313 Mo à elles seules. Une sauvegarde
complète d'avant la réécriture est restée dans `~/ventoux-avant-menage.bundle`.

Git finira malgré tout par regrossir. La suite prévue est un stockage objet
pour les vignettes — **Cloudflare R2** offre 10 Go-mois, un million d'écritures
et un **trafic sortant gratuit**, ce dernier point étant celui qui compte pour
un site qui sert des images.

## Les secrets

Rien de sensible n'entre dans `config/config.json`, qui est suivi par git.

Les identifiants vivent dans `config/local.json`, qui est dans `.gitignore` et
en mode 600. `watcher/config.py` le fusionne récursivement par-dessus la
configuration publique.

```json
{
  "opensky": {"client_id": "...", "client_secret": "..."},
  "drive": {"credentials": "secrets/drive.json", "folder_id": "..."}
}
```

`watcher/publish.py` refuse par sécurité de publier un chemin commençant par
`secrets/` ou un `.json` contenant « drive ». OpenSky et Drive sont facultatifs :
sans compte OpenSky l'archive des avions reste anonyme et plus limitée, sans
clé Drive les photos sont publiées mais pas les extraits vidéo.

Ce fichier n'est pas copié par le script d'installation. Il faut le porter à la
main sur le Pi, une fois.

## Ce qui reste à faire

- Brancher l'alimentation 27 W et lancer l'installation du Pi (28 septembre).
- Raccorder le SSD externe avec `pi_attach_disk.sh` (29 septembre).
- Déclarer la clé de déploiement du Pi en écriture sur le dépôt.
- Porter `config/local.json` sur le Pi.
- Résoudre l'avertissement `Historique distant non rapatrié` : le `git pull
  --rebase` échoue parce que le veilleur remue `data/learning.json` en
  permanence. Sans conséquence tant qu'une seule machine publie, bloquant dès
  que le Mac et le Pi publieront tous les deux.
- Passer les vignettes sur un stockage objet avant que git regrossisse.
- Comprendre pourquoi un feu simulé sur la pente à 578 m n'est pas vu, alors
  que les mêmes feux à 140 m et 183 m sont nommés en six secondes.
- Enregistrer les interruptions de surveillance au moment où elles se
  produisent, au lieu de les reconstituer après coup ([incidents.md](incidents.md)).
