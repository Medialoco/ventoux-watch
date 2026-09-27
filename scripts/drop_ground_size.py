"""Retire les événements nommés par la taille au sol le 27 septembre.

La règle a tourné quatre heures et publié 128 « véhicules » qui étaient des
piétons pour la plupart. Elle est retirée de watcher/naming.py ; il reste à
effacer ce qu'elle a écrit.

On les reconnaît à leur signature plutôt qu'à une liste d'horodatages : seule
cette règle publiait un véhicule à 0,5 de confiance sans que le modèle en ait
confirmé un. Les photos restent sur le disque, comme pour tout événement retiré.

Le premier jet ne cherchait que les événements où le modèle n'avait rien vu du
tout, et il en a manqué vingt et un : quand le modèle voyait une personne trop
large pour en être une, la personne était écartée et la règle prenait le relais
pour dire « véhicule ». La trace gardait donc « person 0.88 » sous un libellé
de véhicule. C'est l'absence de voiture confirmée qui compte, pas l'absence de
détection.

    .venv/bin/python scripts/drop_ground_size.py --pour-de-vrai
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPUIS = "2026-09-27T07:00:00Z"


def fautif(event: dict) -> bool:
    if event.get("type") != "vehicle" or event.get("t", "") < DEPUIS:
        return False
    if abs(float(event.get("confidence") or 0) - 0.5) > 1e-9:
        return False
    detail = event.get("detail") or {}
    if detail.get("correction"):
        # Une correction faite à la main ne se jette jamais.
        return False
    if detail.get("period") != "day":
        # La règle de nuit publie elle aussi à 0,5 quand rien n'est éclairé.
        return False
    vus = (detail.get("measured") or {}).get("seen_as") or []
    return not any(v.split()[0] in {"car", "truck", "bus"} for v in vus)


def main() -> int:
    pour_de_vrai = "--pour-de-vrai" in sys.argv
    chemin = ROOT / "data" / "events.json"
    charge = json.loads(chemin.read_text())
    liste = charge if isinstance(charge, list) else charge.get("events", [])

    vises = [e for e in liste if fautif(e)]
    print(f"{len(vises)} événements à retirer sur {len(liste)}")
    for e in vises[:8]:
        mesure = (e.get("detail") or {}).get("measured") or {}
        print(f"  {e['t']}  {e.get('label')}  {mesure.get('width_m')} x {mesure.get('height_m')} m")
    if len(vises) > 8:
        print(f"  ... et {len(vises) - 8} autres")

    if not pour_de_vrai:
        print("\nEssai à blanc. Relancer avec --pour-de-vrai pour appliquer.")
        return 0

    restants = [e for e in liste if not fautif(e)]
    if isinstance(charge, list):
        charge = restants
    else:
        charge["events"] = restants
    chemin.write_text(json.dumps(charge, ensure_ascii=False, indent=1) + "\n")
    print(f"\nfait : {len(restants)} événements conservés")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
