"""Export d'un YOLO11 vers ONNX. À lancer sur le Mac, pas sur le Pi.

    .venv/bin/python scripts/export_model.py        # nano, celui en service
    .venv/bin/python scripts/export_model.py s m    # les plus gros, pour comparer
"""

import sys
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "models"


def main() -> None:
    tailles = sys.argv[1:] or ["n"]
    DEST.mkdir(parents=True, exist_ok=True)
    for taille in tailles:
        nom = f"yolo11{taille}"
        exported = YOLO(f"{nom}.pt").export(format="onnx", imgsz=640, simplify=True)
        target = DEST / f"{nom}.onnx"
        target.write_bytes(Path(exported).read_bytes())
        print(f"{target}  {target.stat().st_size / 1048576:.1f} Mo")


if __name__ == "__main__":
    main()
