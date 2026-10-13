"""Radio HLS metadata and ffmpeg branch."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from watcher.radio_serveur import note_radio


class TestRadioJson(unittest.TestCase):
    def test_note_radio_live_requires_https_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            note_radio(racine, live=True, public_base="https://radio.example.com/stream")
            fiche = json.loads((racine / "data" / "radio.json").read_text(encoding="utf-8"))
            self.assertTrue(fiche["live"])
            self.assertEqual(fiche["url"], "https://radio.example.com/stream/index.m3u8")

    def test_note_radio_off_without_public_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            note_radio(racine, live=True, public_base="")
            fiche = json.loads((racine / "data" / "radio.json").read_text(encoding="utf-8"))
            self.assertFalse(fiche["live"])
            self.assertEqual(fiche["url"], "")


class TestSortieHls(unittest.TestCase):
    def test_sortie_includes_hls_when_playlist_set(self) -> None:
        from watcher import stream

        with patch.object(stream.subprocess, "Popen") as popen:
            popen.return_value.stdin = object()
            with tempfile.TemporaryDirectory() as tmp:
                playlist = Path(tmp) / "index.m3u8"
                stream._sortie(
                    "rtmp://example/live/key",
                    1280,
                    720,
                    6,
                    "1800k",
                    hls_playlist=playlist,
                )
            args = popen.call_args[0][0]
            self.assertIn("-f", args)
            self.assertIn("hls", args)
            self.assertIn(str(playlist), args)


if __name__ == "__main__":
    unittest.main()
