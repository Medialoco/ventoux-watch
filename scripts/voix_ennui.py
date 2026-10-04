"""Enregistre les quelques mots que le flux dit quand il ne se passe rien.

La machine du Ventoux n'a aucune synthèse vocale et n'en aura pas : elle tourne
déjà à la limite thermique, et installer un moteur de parole pour cinq secondes
de son par vingt minutes serait payer cher une plaisanterie. On enregistre donc
ici, une fois, et on ne livre là-bas que des fichiers.

Le format de sortie est celui que la diffusion manipule déjà — PCM brut, 44 100
hertz, deux voies, seize bits signés — pour qu'au moment de parler il n'y ait
rien à convertir : seulement des octets à additionner.

    .venv/bin/python -m scripts.voix_ennui
    .venv/bin/python -m scripts.voix_ennui --ecoute
    .venv/bin/python -m scripts.voix_ennui --moteur macos

La synthèse est celle de medialoco-tube : le modèle parlant d'OpenAI, appelé une
fois ici, jamais sur le Pi. Les voix de macOS restent en secours, pour une
machine sans clé ou sans réseau.

Deux raisons de préférer l'une à l'autre, et aucune n'est le timbre. La
première est qu'on peut dire à ce modèle *comment* jouer la phrase : l'ennui se
demande, là où macOS ne proposait qu'un choix entre des voix sérieuses et des
voix de dessin animé. La seconde est que la question du droit tombe — les
conditions d'OpenAI laissent la sortie à qui la commande, alors qu'une voix
système sur une chaîne monétisée reste une zone grise.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ECHANTILLONS_S = 44100
VOIES = 2

# Plusieurs phrases, et plusieurs voix. La même réplique toutes les vingt
# minutes pendant une nuit entière cesse d'être une blague et devient une
# alarme ; c'est la variation qui fait qu'on sourit encore à la cinquième.
# Deux occasions de parler, et deux tons. L'ennui traîne, la prise claque :
# la même voix pour les deux ferait du « good catch » une remarque de plus
# alors que c'est le seul moment où la machine a réussi quelque chose.
#
# Et plus Bubbles, Boing ni Bad News. Les trois voix fantaisistes de macOS
# déforment les mots par construction — Bubbles parle sous l'eau, Boing
# rebondit, Bad News chante un enterrement — et à l'antenne on n'y comprenait
# rien. Or une plaisanterie qu'on n'entend pas n'est pas une plaisanterie,
# c'est un bruit, et un bruit sur un flux de surveillance ressemble à une
# panne. Le comique doit être dans la phrase : « absolutely nothing is
# happening » dit à plat est plus drôle que « boooring » dit par une bulle.
#
# Les voyelles étirées restent, elles : elles passent le mot à l'écran et la
# synthèse les allonge vraiment, donc le son suit ce qu'on lit.
#
# Un rôle et non une voix. Ce qui compte à l'écriture est qu'une réplique soit
# traînée ou claquée ; quel timbre s'en charge est une affaire de moteur, et
# changer de moteur ne doit renommer aucun fichier ni rien apprendre au flux.
PLAT, CLAIRE = "plat", "claire"
REPLIQUES = [
    ("ennui", PLAT, "Boooooooring"),
    ("ennui", PLAT, "Still nothing"),
    ("ennui", CLAIRE, "So boooring"),
    ("ennui", CLAIRE, "Nothing. Again"),
    ("ennui", PLAT, "Absolutely nothing is happening"),
    ("ennui", PLAT, "Boooooring"),
    ("attrape", CLAIRE, "Good catch!"),
    ("attrape", PLAT, "Good catch!"),
    ("attrape", CLAIRE, "Got one!"),
    ("attrape", CLAIRE, "Nice one!"),
    ("matin", CLAIRE, "Goooood morning Ventoux!"),
    ("matin", PLAT, "Goooood morning Ventoux!"),
    # Le brouillard tient des demi-journées ici, et pendant ce temps l'image
    # est un mur gris. Le dire de temps en temps est la seule façon de faire
    # comprendre que la caméra n'est pas en panne — et c'est plus drôle que de
    # laisser croire qu'elle l'est.
    ("brouillard", CLAIRE, "Foooooog"),
    ("brouillard", PLAT, "Fog. Again"),
    ("brouillard", PLAT, "Just fooog"),
    ("brouillard", CLAIRE, "I can see nothing at all"),
    # La rediffusion était le seul moment du flux qui faisait peur. Tout
    # s'assombrissait d'un coup, une image floue de surveillance apparaissait
    # au milieu, et « REPLAY » s'écrivait en rouge — la couleur qu'on garde
    # pour les alarmes. Rien de tout cela n'était voulu : on voulait seulement
    # ne pas mentir sur la date. Une voix qui chante le mot dit la même chose
    # et ne fait peur à personne, parce qu'une alarme ne chante pas.
    ("rediff", CLAIRE, "Replaaaayyyyyyy"),
    ("rediff", PLAT, "Replaaaayyyyyyy"),
    ("rediff", CLAIRE, "Replaaaayyy, again"),
    ("rediff", PLAT, "And now, a replaaaayyyyy"),
    # L'ours. Il y a une sculpture de bois debout près du chemin, un ours
    # grandeur nature, 1,73 m sur la carte de scène. Il regarde passer les
    # voitures depuis des années sans rien dire. Une fois de temps en temps son
    # double descend danser sur le rond-point en pleurant, et c'est la seule
    # chose de tout le flux qui ne soit ni une mesure ni une information.
    # Deux occasions et non une : il grogne en descendant, et il crie une fois
    # arrivé. Les trier sur le nom du fichier aurait marché jusqu'au jour où
    # une réplique contient les deux mots.
    ("ours", PLAT, "Grrrrrrrrrr"),
    ("ours", PLAT, "Grrrrooaaarrr"),
    ("ours_cri", PLAT, "THIS IS MY HOME!"),
    ("ours_cri", PLAT, "This is my hoooome!"),
    # Le portrait du Pi, en grand au milieu. C'est lui qui tient le flux,
    # depuis Los Angeles, et on ne le voyait que dans un disque de cent
    # pixels. Quand il prend enfin la place, on le remercie.
    ("machine", CLAIRE, "Thanks Raspberry!"),
    ("machine", PLAT, "Thanks Raspberry!"),
    # Dogmazic, le même numéro : le logo au milieu, et on les remercie.
    ("dogmazic", CLAIRE, "Thanks Dogmazic!"),
    ("dogmazic", PLAT, "Thanks Dogmazic!"),
    # Une pensée, dite une fois par jour et tenue hors du tableau du site.
    # Le nom est dit dans les deux sens : on ne sait pas lequel est le sien,
    # et c'est précisément ce qu'on lui dit.
    ("pensee", PLAT,
     "To my very good friend David Vincent or Vincent David or David Vincent, Je pense à toi."),
    ("normandie", CLAIRE, "Big-UP à la Normandie !!!!"),
    ("normandy", CLAIRE, "Big up to the Normandy!"),
    # Le mot du redémarrage. La porteuse est ajoutée après, dans le fichier :
    # le modèle dit le mot clairement, le traitement le rend un peu électronique.
    ("deploi", PLAT, "Deployed"),
]


# Les rapports de fréquence d'une cloche, qui n'ont rien d'harmonique : c'est
# justement ce qui fait qu'une cloche sonne comme une cloche et pas comme une
# flûte. Le « hum » en dessous de la fondamentale, la tierce mineure au-dessus,
# puis la quinte, l'octave et ce qui traîne plus haut.
PARTIELS = [(0.56, 0.9, 2.2), (0.92, 0.6, 1.8), (1.00, 1.0, 1.6), (1.19, 0.5, 1.1),
            (1.71, 0.35, 0.8), (2.00, 0.3, 0.7), (2.74, 0.2, 0.45), (3.76, 0.12, 0.3)]
# Un sol aigu. Plus bas, la cloche pèse et annonce un malheur ; plus haut, elle
# tinte comme une notification de téléphone.
CLOCHE_HZ = 784.0


def cloche(duree: float = 1.9, hauteur: float = CLOCHE_HZ) -> np.ndarray:
    """Une cloche, fabriquée ici. PCM entier signé, deux voies.

    Faite et non trouvée : c'est trois lignes d'arithmétique, et le premier
    octobre au matin un direct est tombé parce qu'un son venait d'ailleurs.
    Celui-ci n'appartient à personne.

    Chaque partiel s'éteint à son rythme — les aigus d'abord, le bourdon en
    dernier. Une décroissance unique pour tous donnerait un accord d'orgue qu'on
    coupe, pas une cloche qu'on frappe.
    """
    t = np.arange(int(duree * ECHANTILLONS_S), dtype=np.float32) / ECHANTILLONS_S
    onde = np.zeros_like(t)
    for rapport, poids, tenue in PARTIELS:
        onde += poids * np.sin(2 * np.pi * hauteur * rapport * t) * np.exp(-t / tenue)
    # Une attaque de trois millisecondes : sans elle le premier échantillon
    # saute de zéro à pleine amplitude, et ce saut s'entend comme un clic.
    attaque = min(len(onde), int(0.003 * ECHANTILLONS_S))
    onde[:attaque] *= np.linspace(0.0, 1.0, attaque, dtype=np.float32)
    onde *= 0.55 / max(float(np.abs(onde).max()), 1e-6)
    return np.repeat((onde * 32767).astype(np.int16), VOIES)


def electronise(pcm: bytes, profondeur: float = 0.22, hz: float = 90.0) -> bytes:
    """Un filet de porteuse à quatre-vingt-dix hertz.

    Le mot reste un mot : les quatre cinquièmes du signal passent tels quels,
    le reste est multiplié par une sinusoïde. C'est une modulation en anneau
    tenue très en retrait, assez pour qu'on entende une machine, pas assez
    pour qu'on cesse de comprendre.
    """
    son = np.frombuffer(pcm, np.int16).astype(np.float32)
    n = son.size // VOIES
    if n == 0:
        return pcm
    porteuse = np.sin(2 * np.pi * hz * np.arange(n, dtype=np.float32) / ECHANTILLONS_S)
    for voie in range(VOIES):
        sec = son[voie::VOIES]
        son[voie::VOIES] = sec * (1.0 - profondeur) + sec * porteuse * profondeur
    crete = float(np.abs(son).max())
    if crete > 32767 * 0.92:
        son *= (32767 * 0.92) / crete
    return np.clip(son, -32768, 32767).astype(np.int16).tobytes()


def _mele(cloche_pcm: np.ndarray, voix: bytes, retard_s: float) -> bytes:
    """Pose la voix sur la cloche, un peu après le coup.

    Ensemble dans un seul fichier plutôt qu'enchaînés par la diffusion : le
    mélangeur du flux ne tient qu'une réplique à la fois, et lui en faire tenir
    deux pour une plaisanterie serait beaucoup de risque pour peu de chose.
    """
    debut = int(retard_s * ECHANTILLONS_S) * VOIES
    dessus = np.frombuffer(voix, np.int16)
    total = max(len(cloche_pcm), debut + len(dessus))
    melange = np.zeros(total, np.float32)
    melange[:len(cloche_pcm)] += cloche_pcm
    melange[debut:debut + len(dessus)] += dessus
    # La somme dépasse le plafond que la voix seule respectait : une cloche à
    # 0,55 plus une voix à 0,60 montent à 0,88, et la musique ajoutera encore
    # la sienne par-dessus. On redescend l'ensemble plutôt que d'écrêter — un
    # écrêtage sur une attaque de cloche s'entend comme un craquement, et un
    # craquement sur un flux de surveillance ressemble à une panne.
    crete = float(np.abs(melange).max()) / 32768
    if crete > PLAFOND:
        melange *= PLAFOND / crete
    return np.clip(melange, -32768, 32767).astype(np.int16).tobytes()


def _nom(voix: str, texte: str) -> str:
    return re.sub(r"[^\w]+", "_", f"{voix}-{texte}").strip("_").lower()[:60] + ".raw"


# Le débit, en mots par minute, pour le secours macOS. Une machine qui s'ennuie
# parle lentement, une machine qui vient de repérer quelque chose claque sa
# phrase. C'est le seul réglage de jeu que « say » accepte.
CADENCES = {"ennui": 120, "brouillard": 120, "matin": 160, "attrape": 180,
            # Lentement : c'est une voyelle tenue, pas une phrase. « say » ne
            # chantera pas, mais au moins il traînera.
            "rediff": 110,
            # Un ours ne parle pas vite.
            "ours": 100, "ours_cri": 100,
            "machine": 170, "dogmazic": 170,
            "pensee": 150, "normandie": 160, "normandy": 160, "deploi": 150}

# La consigne de jeu, envoyée avec chaque phrase. C'est ce qu'on ne pouvait pas
# faire avec les voix système : le ton s'y choisissait en changeant de personne,
# d'où les voix de dessin animé pour obtenir un peu de comique et des mots qu'on
# ne comprenait plus. Ici le timbre reste sérieux et c'est le jeu qui porte la
# plaisanterie, ce qui est la bonne répartition.
JEU = {
    "ennui": "Profoundly, terminally bored. Flat, deadpan, unhurried, almost "
             "sighing. Drag the stretched vowels out slowly. You are a machine "
             "that has watched an empty mountain for an hour and has given up "
             "expecting anything. Never cheerful, never ironic — just tired.",
    "brouillard": "Resigned and flat. There is nothing to see and there has "
                  "been nothing to see for hours. Drag the stretched vowels. "
                  "State it as a fact you have stopped minding.",
    "attrape": "Genuinely delighted and a little surprised, quick and bright, "
               "like finally spotting something after a long empty wait. Warm, "
               "not loud, and over in a second.",
    "matin": "Warm and welcoming, a radio host opening the morning. Stretch "
             "the long vowel generously. Unhurried but awake.",
    "rediff": "Sing it, actually sing — a silly little descending melody on "
              "the stretched vowel, like a jingle announcing an old clip on a "
              "late-night show. Light, amused, slightly ridiculous and "
              "completely harmless. Never dramatic, never ominous.",
    "ours_cri": "A big wooden bear bellowing through tears. Sobbing openly, "
                "voice cracking, broken-hearted and absolutely furious about "
                "it at the same time. Wail the words out at the top of his "
                "lungs, like a creature who has lived on this mountain far "
                "longer than the road has.",
    "ours": "A big wooden bear, low and gravelly, growling through tears. "
            "Sobbing openly, voice cracking, broken-hearted and absolutely "
            "furious about it at the same time. Roll the growl deep in the "
            "chest, then wail the words out like a creature who has lived on "
            "this mountain far longer than the road has.",
    "machine": "Warm, grateful, a little giddy. You are thanking the small "
               "computer that watches a mountain day and night. Bright and "
               "sincere, not sarcastic. Say exactly the two words Thanks "
               "Raspberry and then stop. No period, no exclamation, never "
               "say the word dot. Over in a second and a half.",
    "dogmazic": "Warm, grateful, a little giddy. You are thanking the free "
                "music archive that fills the mountain watch. Bright and "
                "sincere. Say Thanks Dogmazic! with a cheerful lift. The "
                "exclamation is energy, never the word dot. Over in a "
                "second and a half.",
    "pensee": "Warm, quiet, and sincere, like a letter read aloud to one "
              "person. Say the name twice, first David Vincent, then Vincent "
              "David, then David Vincent again, clearly, so both orders are "
              "heard. Then the French sentence Je pense à toi, in French, "
              "tender and unhurried. Never comic, never sung, never loud.",
    "normandie": "A big cheerful shout, proud and bright, like a radio drop "
                 "for home. Say Big-UP à la Normandie with four beats of joy "
                 "on the exclamation. French on Normandie. Never ominous, "
                 "never a whisper. Over in two seconds.",
    "normandy": "A big cheerful shout in English, proud and bright, like a "
                "radio drop for home. Say Big up to the Normandy! with a "
                "lift on Normandy. Never ominous, never a whisper. Over in "
                "two seconds.",
    "salle": "Adult male, clear, and a little delighted by a very small "
             "piece of arithmetic. French. Say exactly the words given and "
             "nothing else, evenly, as one piece of a sentence that will be "
             "assembled later. No greeting, no extra word, never say the "
             "word dot.",
    "deploi": "Say the single word Deployed, clear and even, like a machine "
              "confirming that it has arrived. Flat, intelligible, about one "
              "second. No exclamation. Never say the word dot.",
}

# Les voix, par rôle. « ash » est celle dont medialoco-tube se sert pour sa
# narration ; « nova » est claire et vive, ce que la prise demande.
VOIX = {
    "openai": {PLAT: "ash", CLAIRE: "nova"},
    "macos": {PLAT: "Daniel", CLAIRE: "Samantha"},
}
MODELE = "gpt-4o-mini-tts"
PARLE_URL = "https://api.openai.com/v1/audio/speech"


def cle_openai() -> str:
    """La clé, prise dans le fichier des secrets ou dans l'environnement.

    Jamais dans « config/config.json », qui est suivi par git. « local.json »
    est en 600 et dans le .gitignore, et c'est déjà là que vivent les
    identifiants OpenSky et la clé de diffusion.
    """
    fichier = ROOT / "config" / "local.json"
    if fichier.exists():
        cle = json.loads(fichier.read_text(encoding="utf-8")).get("openai", {}).get("cle")
        if cle:
            return str(cle)
    return os.environ.get("OPENAI_API_KEY", "")


def _explique(code: int, corps: str) -> str:
    """Ce que veut dire le refus, en clair.

    Le piège habituel est une clé parfaitement valide sur un compte sans
    crédit : l'abonnement ChatGPT ne paie pas l'interface de programmation,
    les deux se facturent séparément, et le 429 brut ne le dit pas.
    """
    if code == 429 and "insufficient_quota" in corps:
        return ("Le compte OpenAI n'a plus de crédit d'interface.\n"
                "  → en ajouter sur platform.openai.com/settings/organization/billing\n"
                "  → un abonnement ChatGPT n'en donne pas, c'est facturé à part\n"
                "  → ces seize répliques coûtent moins d'un centime")
    if code == 401:
        return ("OpenAI a refusé la clé. Vérifier « openai.cle » dans "
                "config/local.json, espaces compris.")
    return f"OpenAI a répondu {code} : {corps[:300]}"


def _demande(texte: str, voix: str, jeu: str) -> bytes:
    corps = json.dumps({"model": MODELE, "voice": voix, "input": texte,
                        "instructions": jeu, "response_format": "wav"}).encode()
    requete = urllib.request.Request(
        PARLE_URL, data=corps,
        headers={"Authorization": f"Bearer {cle_openai()}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requete, timeout=120) as reponse:
            return reponse.read()
    except urllib.error.HTTPError as erreur:
        raise SystemExit(_explique(erreur.code,
                                   erreur.read().decode("utf-8", "replace")))


def mesure(wav: bytes) -> tuple[float, float]:
    """Le niveau de la parole et la crête du fichier, entre zéro et un.

    La parole se mesure silences exclus : on découpe en tranches de cinquante
    millisecondes et on prend le neuvième décile des valeurs efficaces. La
    moyenne sur tout le fichier dirait autre chose — une phrase précédée d'une
    seconde de blanc paraîtrait plus faible qu'elle n'est, et on la remonterait
    trop. Le décile ignore les blancs sans se laisser emporter par un claquement
    isolé, ce qu'un maximum ferait.
    """
    with wave.open(io.BytesIO(wav)) as f:
        return mesure_pcm(f.readframes(f.getnframes()),
                          f.getnchannels(), f.getframerate())


def mesure_pcm(pcm: bytes, voies: int = VOIES,
               cadence: int = ECHANTILLONS_S) -> tuple[float, float]:
    """La même mesure, sur des octets déjà déballés."""
    x = np.frombuffer(pcm, np.int16).astype(np.float32)
    if not len(x):
        return 0.0, 0.0
    x /= 32768
    pas = max(1, int(0.05 * cadence) * voies)
    utile = x[:len(x) - len(x) % pas]
    if not len(utile):
        utile, pas = x, len(x)
    efficaces = np.sqrt((utile.reshape(-1, pas) ** 2).mean(axis=1))
    return float(np.percentile(efficaces, 90)), float(np.abs(x).max())


# En dessous, il ne s'est rien dit. Ce n'est pas un seuil de goût : une voix,
# même soufflée, passe largement au-dessus, et seul un fichier vide descend là.
MUET = 0.005
# Le niveau de parole visé, et le plafond.
#
# La cible est de l'arithmétique et non un goût. Pour qu'une phrase se
# comprenne par-dessus un fond, il lui faut environ six décibels d'avance ;
# c'est une donnée d'audition, pas un réglage de mixeur. Les morceaux tournent
# autour de 0,22 efficace et le flux les baisse à 0,25 pendant qu'on parle,
# donc le fond pose 0,055 : une parole à 0,12 passe sept décibels au-dessus.
#
# Le plafond vient du même calcul par l'autre bout : le mélangeur additionne,
# une musique à fond pose 0,25 en crête, et 0,60 + 0,25 laisse encore de la
# marge avant l'écrêtage.
CIBLE_RMS, PLAFOND = 0.12, 0.60


def gain(wav: bytes) -> float:
    """De combien remonter ce fichier pour qu'il parle comme les autres.

    Un gain unique pour toutes les répliques reconduisait les écarts de jeu : à
    qui on demande d'être fatigué, le modèle chuchote, et « Boooooooring »
    sortait six fois plus faible que « Good catch! ». Sous une musique
    seulement baissée à 35 %, un murmure redevient inaudible — c'est la plainte
    du départ par un autre chemin.

    Calculé ici plutôt que confié à loudnorm, essayé d'abord : la norme R128
    gèle ses mesures sur des fenêtres de trois secondes et nos répliques en
    durent deux, silences compris. Elle rendait six fichiers sur seize *plus*
    faibles qu'avant, sans rien signaler. Deux lignes d'arithmétique qu'on peut
    vérifier valent mieux qu'un instrument de mesure hors de sa plage.
    """
    parole, crete = mesure(wav)
    return min(CIBLE_RMS / max(parole, 1e-6), PLAFOND / max(crete, 1e-6))


def _parle_openai(texte: str, voix: str, jeu: str, essais: int = 3) -> bytes:
    """Un WAV dit par le modèle, et dont on a vérifié qu'il contient une voix.

    Le modèle rend parfois un fichier bien formé et parfaitement silencieux :
    « Foooooog » est revenu vide au premier jet, sans erreur et avec la bonne
    durée. Livré tel quel il aurait fait, à l'antenne, un mot affiché sur rien
    — exactement la panne qu'on essaie d'éviter, et invisible à la relecture du
    code puisque le code avait bien fonctionné. On regarde donc ce qu'on a reçu
    plutôt que de croire le code de retour, et on redemande.
    """
    for essai in range(essais):
        wav = _demande(texte, voix, jeu)
        if mesure(wav)[0] >= MUET:
            return wav
        print(f"    (réponse muette pour « {texte} », on redemande)")
    raise SystemExit(f"OpenAI n'a rien dit pour « {texte} » en {essais} essais.")


def grave(role: str, texte: str, cible: Path, quand: str,
          moteur: str = "openai") -> float:
    """Dit la phrase et la pose en PCM brut. Rend sa durée en secondes."""
    with tempfile.TemporaryDirectory() as dossier:
        if moteur == "openai":
            dit = Path(dossier) / "dit.wav"
            dit.write_bytes(_parle_openai(texte, VOIX[moteur][role], JEU[quand]))
        else:
            aiff = Path(dossier) / "dit.aiff"
            subprocess.run(["say", "-v", VOIX["macos"][role],
                            "-r", str(CADENCES[quand]), "-o", str(aiff), texte],
                           check=True)
            dit = Path(dossier) / "dit.wav"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-i", str(aiff), str(dit)], check=True)
        g = gain(dit.read_bytes())
        _encode(dit, cible, g)
        # Et on écoute ce qu'on vient d'écrire plutôt que de croire le calcul.
        #
        # Le gain était juste et la sortie arrivait pourtant trois décibels
        # trop bas, à 0,085 pour 0,12 demandés : ffmpeg atténue d'un facteur
        # racine de deux en passant la mono en stéréo. On pourrait écrire ce
        # facteur ici — ce serait exact aujourd'hui, faux le jour où la voix
        # arrive déjà en stéréo, et personne ne s'en apercevrait puisque rien
        # ne casse. Mesurer le résultat se moque de savoir ce que fait ffmpeg.
        parole, crete = mesure_pcm(cible.read_bytes())
        if parole > MUET and abs(parole - CIBLE_RMS) > 0.05 * CIBLE_RMS:
            _encode(dit, cible,
                    g * min(CIBLE_RMS / parole, PLAFOND / max(crete, 1e-6)))
    return cible.stat().st_size / (ECHANTILLONS_S * VOIES * 2)


def _encode(source: Path, cible: Path, g: float) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-af", f"volume={g:.4f},aresample={ECHANTILLONS_S}",
         "-f", "s16le", "-ar", str(ECHANTILLONS_S), "-ac", str(VOIES), str(cible)],
        check=True)


def enregistre(dossier: Path, ecoute: bool = False, moteur: str = "openai",
               seulement: str = "") -> int:
    if moteur == "openai" and not cle_openai():
        print("Pas de clé OpenAI : poser « openai.cle » dans config/local.json,\n"
              "ou bien --moteur macos pour les voix du système.")
        return 1
    if moteur == "macos" and shutil.which("say") is None:
        print("« say » n'existe que sur macOS : à lancer depuis le Mac, pas depuis le Pi.")
        return 1
    dossier.mkdir(parents=True, exist_ok=True)
    # Une gravure partielle garde les répliques déjà là : on n'a pas à
    # tout redire pour en ajouter deux.
    deja = []
    if seulement:
        try:
            deja = json.loads((dossier / "voix.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            deja = []
        deja = [f for f in deja if f.get("quand") != seulement]
    fiches = list(deja)
    for quand, voix, texte in REPLIQUES:
        if seulement and quand != seulement:
            continue
        cible = dossier / _nom(f"{quand}-{voix}", texte)
        duree = grave(voix, texte, cible, quand, moteur)
        if quand == "deploi":
            cible.write_bytes(electronise(cible.read_bytes()))
            duree = cible.stat().st_size / (ECHANTILLONS_S * VOIES * 2)
        if quand == "attrape":
            # La cloche d'abord, la voix dans sa résonance. L'inverse ferait
            # une annonce suivie d'un bruit ; là, c'est un sourire.
            cible.write_bytes(_mele(cloche(), cible.read_bytes(), 0.42))
            duree = cible.stat().st_size / (ECHANTILLONS_S * VOIES * 2)
        fiches.append({"fichier": cible.name, "texte": texte, "voix": voix,
                       "quand": quand, "duree": round(duree, 3),
                       "timbre": VOIX[moteur][voix]})
        print(f"  {duree:4.1f} s  {quand:10s} {VOIX[moteur][voix]:9s} « {texte} »")
        if ecoute:
            subprocess.run(["ffplay", "-hide_banner", "-loglevel", "error", "-autoexit",
                            "-f", "s16le", "-ar", str(ECHANTILLONS_S), "-ac", str(VOIES),
                            str(cible)], check=False)
    # Et la cloche seule, deux fois sur six environ : une prise sans commentaire
    # est plus légère qu'une prise commentée, et c'est ce qu'on cherche.
    if not seulement or seulement == "attrape":
        for nom, hauteur in (("attrape_cloche", CLOCHE_HZ),
                             ("attrape_cloche_haute", CLOCHE_HZ * 1.5)):
            seule = dossier / f"{nom}.raw"
            seule.write_bytes(cloche(hauteur=hauteur).tobytes())
            duree = seule.stat().st_size / (ECHANTILLONS_S * VOIES * 2)
            fiches.append({"fichier": seule.name, "texte": "(cloche)",
                           "voix": "maison", "quand": "attrape",
                           "duree": round(duree, 3)})
            print(f"  {duree:4.1f} s  attrape  maison     « cloche {hauteur:.0f} Hz »")

    (dossier / "voix.json").write_text(
        json.dumps(fiches, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(fiches)} répliques dans {dossier}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--dossier", default=str(ROOT / "data" / "voix"))
    parseur.add_argument("--ecoute", action="store_true", help="les jouer en les gravant")
    parseur.add_argument("--moteur", choices=sorted(VOIX), default="openai")
    parseur.add_argument("--quand", default="",
                        help="ne graver que cette occasion, et la fondre "
                             "dans voix.json")
    args = parseur.parse_args(argv)
    return enregistre(Path(args.dossier), args.ecoute, args.moteur,
                      seulement=args.quand)


if __name__ == "__main__":
    raise SystemExit(main())
