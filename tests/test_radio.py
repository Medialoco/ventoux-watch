"""Radio HLS metadata and ffmpeg branch."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from watcher.radio_serveur import (
    habille_playlist,
    note_radio,
    publie_morceau,
    titre_du_morceau,
    veut_page_html,
)


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


class TestCreditRadio(unittest.TestCase):
    def test_titre_porte_artiste_chanson_et_licence(self) -> None:
        ligne = titre_du_morceau({
            "auteur": "Nemeton",
            "titre": "01nocti27",
            "licence": "CC BY 4.0",
        })
        self.assertEqual(ligne, "Nemeton — 01nocti27 · CC BY 4.0")

    def test_playlist_nomme_chaque_segment(self) -> None:
        brut = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            "#EXTINF:2.000,\n"
            "seg_00001.ts\n"
        )
        titre = "Nemeton — 01nocti27 · CC BY 4.0"
        texte = habille_playlist(brut, titre)
        self.assertIn(f"#EXTINF:2.000,{titre}", texte)
        self.assertIn('URI="now.json"', texte)

    def test_publie_morceau_ecrit_now_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dossier = Path(tmp)
            publie_morceau(dossier, {
                "auteur": "Naxar",
                "titre": "Night Sky",
                "licence": "CC BY-SA 3.0",
                "url": "https://play.dogmazic.net/song.php?action=show_song&song_id=1",
                "url_licence": "https://creativecommons.org/licenses/by-sa/3.0/",
                "pochette": "pochettes/naxar.jpg",
            })
            fiche = json.loads((dossier / "now.json").read_text(encoding="utf-8"))
            self.assertEqual(fiche["artiste"], "Naxar")
            self.assertEqual(fiche["titre"], "Night Sky")
            self.assertEqual(fiche["licence"], "CC BY-SA 3.0")
            self.assertEqual(fiche["pochette"], "pochettes/naxar.jpg")


class TestPageRadio(unittest.TestCase):
    def test_veut_page_html(self) -> None:
        self.assertTrue(veut_page_html("text/html,application/xhtml+xml"))
        self.assertFalse(veut_page_html("application/vnd.apple.mpegurl"))
        self.assertFalse(veut_page_html("*/*"))

    def test_index_m3u8_navigateur_ou_lecteur(self) -> None:
        import urllib.error
        import urllib.request

        from watcher.radio_serveur import RadioServeur

        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            (racine / "index.m3u8").write_text("#EXTM3U\n#EXT-X-VERSION:3\n", encoding="utf-8")
            srv = RadioServeur(racine)
            srv.demarre(28767)
            try:
                html = urllib.request.urlopen(
                    urllib.request.Request(
                        "http://127.0.0.1:28767/index.m3u8",
                        headers={"Accept": "text/html,application/xhtml+xml"},
                    ),
                    timeout=2,
                ).read()
                self.assertIn(b"FREETECHNORADIO", html)
                pl = urllib.request.urlopen(
                    urllib.request.Request(
                        "http://127.0.0.1:28767/index.m3u8",
                        headers={"Accept": "*/*"},
                    ),
                    timeout=2,
                ).read()
                self.assertTrue(pl.startswith(b"#EXTM3U"))
            except urllib.error.URLError as err:
                self.skipTest(f"port 28767 indisponible : {err}")
            finally:
                srv.ferme()


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
