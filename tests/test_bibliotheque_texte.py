"""Le compte et la durée de la bibliothèque s'écrivent ensemble, partout."""

import unittest
from pathlib import Path

from scripts.bibliotheque_texte import ecris, en_heures_minutes, mots_en, mots_fr, phrases


class MotsTests(unittest.TestCase):
    def test_the_french_rounds_the_way_the_page_already_speaks(self):
        self.assertEqual(mots_fr(1), "un")
        self.assertEqual(mots_fr(21), "vingt et un")
        self.assertEqual(mots_fr(71), "soixante et onze")
        self.assertEqual(mots_fr(80), "quatre-vingts")
        self.assertEqual(mots_fr(81), "quatre-vingt-un")
        self.assertEqual(mots_fr(158), "cent cinquante-huit")
        self.assertEqual(mots_fr(200), "deux cents")
        self.assertEqual(mots_fr(201), "deux cent un")

    def test_the_english_keeps_the_and(self):
        self.assertEqual(mots_en(14), "fourteen")
        self.assertEqual(mots_en(13), "thirteen")
        self.assertEqual(mots_en(158), "one hundred and fifty-eight")

    def test_sixty_minutes_become_an_hour(self):
        self.assertEqual(en_heures_minutes(14 * 3600 + 13 * 60), (14, 13))
        self.assertEqual(en_heures_minutes(4 * 3600), (4, 0))
        self.assertEqual(en_heures_minutes(59.6 * 60), (1, 0))


class EcritureTests(unittest.TestCase):
    def _fausses_pages(self, dossier: Path) -> None:
        (dossier / "site").mkdir()
        (dossier / "site" / "app.js").write_text(
            '    musicLead: "prefix. find the file. OLD EN. The playlist is public.",\n'
            '    heroMusic: "OLD of free music stays.",\n'
            '    musicLead: "préfixe. trouver le fichier. ANCIEN FR. La playlist est publique.",\n'
            '    heroMusic: "ANCIEN de musique libre reste.",\n',
            encoding="utf-8")
        (dossier / "site" / "index.html").write_text(
            "<p>find the file. OLD EN. The playlist is public.</p>\n",
            encoding="utf-8")
        lien = (" [Mont Serein 002](https://play.dogmazic.net/albums.php?"
                "action=show&album=11242)")
        (dossier / "README.md").write_text(
            f"playlist_id=4803). ANCIEN FR{lien}, suite.\n", encoding="utf-8")
        (dossier / "README.en.md").write_text(
            f"playlist_id=4803). OLD EN{lien}, rest.\n", encoding="utf-8")

    def test_count_and_duration_land_in_every_surface_and_stay_put(self):
        import tempfile
        with tempfile.TemporaryDirectory() as brut:
            dossier = Path(brut)
            self._fausses_pages(dossier)
            dit = ecris(158, 14 * 3600 + 13 * 60, 4 * 3600, dossier)
            une = ecris(158, 14 * 3600 + 13 * 60, 4 * 3600, dossier)
            self.assertEqual(dit, une)
            app = (dossier / "site" / "app.js").read_text(encoding="utf-8")
            page = (dossier / "site" / "index.html").read_text(encoding="utf-8")
            lu = (dossier / "README.md").read_text(encoding="utf-8")
            en = (dossier / "README.en.md").read_text(encoding="utf-8")
            self.assertIn(dit["lead_fr"], app)
            self.assertIn(dit["lead_en"], app)
            self.assertIn(dit["lead_en"], page)
            self.assertIn(dit["hero_fr"], app)
            self.assertIn(dit["hero_en"], app)
            self.assertIn(dit["readme_fr"], lu)
            self.assertIn(dit["readme_en"], en)
            self.assertNotIn("OLD EN", app + page + en)
            self.assertNotIn("ANCIEN FR", app + lu)
            self.assertIn("Quatorze heures et treize minutes", dit["lead_fr"])
            self.assertIn("Fourteen hours and thirteen minutes", dit["lead_en"])
            self.assertIn("Quatre heures en sont", dit["lead_fr"])
            self.assertIn("Four hours of that are", dit["lead_en"])
            self.assertEqual(
                phrases(158, 14 * 3600 + 13 * 60, 4 * 3600)["readme_fr"],
                dit["readme_fr"])
