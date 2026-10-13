"""Écrit l'URL HTTPS du tunnel dans config/radio_public.env (Pi, hors git)."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: set_radio_public_url.py https://…")
    url = sys.argv[1].rstrip("/")
    root = Path(__file__).resolve().parents[1]
    env = root / "config" / "radio_public.env"
    env.parent.mkdir(parents=True, exist_ok=True)
    texte = f"VENTOUX_RADIO_PUBLIC_URL={url}\n"
    if env.is_file() and env.read_text(encoding="utf-8") == texte:
        return
    env.write_text(texte, encoding="utf-8")


if __name__ == "__main__":
    main()
