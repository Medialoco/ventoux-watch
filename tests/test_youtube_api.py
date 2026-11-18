"""Le direct se rouvre par l'API quand YouTube l'a terminé."""

import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

from watcher import youtube_api
from watcher.stream import REOUVRE_APRES_S, REOUVRE_PAUSE_S, faut_rouvrir_par_l_api


class FauxYouTube:
    """Répond comme l'API, et garde la trace de ce qu'on lui demande."""

    def __init__(self, actives=(), prevues=(), etats=("ready",), refuse=None):
        self.actives = list(actives)
        self.prevues = list(prevues)
        self.etats = list(etats)
        self.refuse = refuse
        self.appels: list[tuple[str, str, dict]] = []

    def __call__(self, methode, url, donnees, entetes):
        if url.startswith(youtube_api.JETON_URL):
            return json.dumps({"access_token": "acces"}).encode()
        chemin, _, requete = url[len(youtube_api.API) + 1:].partition("?")
        params = dict(urllib.parse.parse_qsl(requete))
        self.appels.append((methode, chemin, params))
        if self.refuse and chemin == self.refuse:
            raise urllib.error.HTTPError(url, 403, "refus", {}, io.BytesIO(b"quota"))
        if chemin == "liveStreams":
            return json.dumps({"items": [
                {"id": "autre", "cdn": {"ingestionInfo": {"streamName": "x"}}},
                {"id": "flux", "cdn": {"ingestionInfo": {"streamName": "cle"}}},
            ]}).encode()
        if chemin == "liveBroadcasts" and methode == "GET" and "id" in params:
            etat = self.etats.pop(0) if len(self.etats) > 1 else self.etats[0]
            return json.dumps({"items": [{"status": {"lifeCycleStatus": etat}}]}).encode()
        if chemin == "liveBroadcasts" and methode == "GET":
            liste = {"active": self.actives, "upcoming": self.prevues,
                     "completed": [{"snippet": {"title": "Titre d'hier",
                                                "description": "Desc"},
                                    "status": {"privacyStatus": "public"}}]}
            return json.dumps({"items": liste[params["broadcastStatus"]]}).encode()
        if chemin == "liveBroadcasts" and methode == "POST":
            corps = json.loads(donnees)
            assert corps["contentDetails"]["enableAutoStart"] is True
            assert corps["contentDetails"]["enableAutoStop"] is False
            assert corps["snippet"]["title"] == "Titre d'hier"
            return json.dumps({"id": "neuve"}).encode()
        return b"{}"

    def faits(self):
        return [(m, c) for m, c, _ in self.appels if m == "POST"]


class RouvreTests(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.racine = Path(self.dossier.name)
        (self.racine / "secrets").mkdir()
        (self.racine / "config").mkdir()
        (self.racine / "secrets" / "youtube_oauth.json").write_text(json.dumps(
            {"client_id": "id", "client_secret": "s", "refresh_token": "r"}))
        (self.racine / "config" / "local.json").write_text(json.dumps(
            {"youtube": {"key": "cle"}}))

    def tearDown(self):
        self.dossier.cleanup()

    def test_cree_attache_et_laisse_demarrer_seul(self):
        yt = FauxYouTube(etats=("ready", "live"))
        numero = youtube_api.rouvre(self.racine, yt, dort=lambda _s: None)
        self.assertEqual(numero, "neuve")
        self.assertEqual(yt.faits(), [("POST", "liveBroadcasts"),
                                      ("POST", "liveBroadcasts/bind")])
        bind = [p for m, c, p in yt.appels if c == "liveBroadcasts/bind"][0]
        self.assertEqual(bind["streamId"], "flux")

    def test_force_le_direct_si_youtube_ne_demarre_pas(self):
        yt = FauxYouTube(etats=("ready",))
        self.assertEqual(youtube_api.rouvre(self.racine, yt, dort=lambda _s: None), "neuve")
        self.assertIn(("POST", "liveBroadcasts/transition"), yt.faits())

    def test_ne_touche_a_rien_si_deja_en_direct(self):
        yt = FauxYouTube(actives=[{"id": "vive", "contentDetails": {"boundStreamId": "flux"}}])
        self.assertEqual(youtube_api.rouvre(self.racine, yt, dort=lambda _s: None), "vive")
        self.assertEqual(yt.faits(), [])

    def test_reprend_une_diffusion_prevue_au_lieu_d_en_creer(self):
        yt = FauxYouTube(prevues=[{"id": "prevue", "contentDetails": {"boundStreamId": "flux"}}],
                         etats=("live",))
        self.assertEqual(youtube_api.rouvre(self.racine, yt, dort=lambda _s: None), "prevue")
        self.assertEqual(yt.faits(), [])

    def test_un_refus_ne_leve_pas(self):
        yt = FauxYouTube(refuse="liveStreams")
        with self.assertLogs("youtube_api", "ERROR"):
            self.assertIsNone(youtube_api.rouvre(self.racine, yt, dort=lambda _s: None))

    def test_sans_autorisation_rien_ne_part(self):
        (self.racine / "secrets" / "youtube_oauth.json").unlink()
        yt = FauxYouTube()
        self.assertIsNone(youtube_api.rouvre(self.racine, yt))
        self.assertEqual(yt.appels, [])


class RythmeTests(unittest.TestCase):
    def test_pas_avant_deux_minutes(self):
        self.assertFalse(faut_rouvrir_par_l_api(1000.0, 0.0, 1000.0 + REOUVRE_APRES_S - 1))
        self.assertTrue(faut_rouvrir_par_l_api(1000.0, 0.0, 1000.0 + REOUVRE_APRES_S))

    def test_un_essai_par_quart_d_heure(self):
        self.assertFalse(faut_rouvrir_par_l_api(0.0, 5000.0, 5000.0 + REOUVRE_PAUSE_S - 1))
        self.assertTrue(faut_rouvrir_par_l_api(0.0, 5000.0, 5000.0 + REOUVRE_PAUSE_S))


if __name__ == "__main__":
    unittest.main()
