"""Écrit radio_public.env depuis radio.public_url (config + local.json)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.config import load_config  # noqa: E402


def main() -> None:
    cfg = load_config(ROOT)
    radio = cfg.get("radio") or {}
    url = (radio.get("public_url") or "").strip().rstrip("/")
    if not url:
        host = (radio.get("tunnel_hostname") or "").strip()
        if host:
            host = host.removeprefix("https://").removeprefix("http://").rstrip("/")
            url = f"https://{host}"
    if not url:
        return
    from scripts.set_radio_public_url import write_radio_public_url  # noqa: WPS433

    write_radio_public_url(ROOT, url)


if __name__ == "__main__":
    main()
