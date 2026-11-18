"""Une entrée figée ne doit jamais figer l'antenne."""

import inspect
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from watcher import stream


class EntreeTests(unittest.TestCase):
    def test_le_mont_serein_a_un_delai_reseau(self):
        entree = inspect.getsource(stream._entree)
        self.assertIn('"-rw_timeout"', entree)
        self.assertLess(entree.index('"-rw_timeout"'), entree.index('"-i", url'))

    def test_la_garde_tue_une_lecture_bloquee(self):
        muet = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE)
        garde = stream.GardeEntree(delai_s=0.3, pas_s=0.05)
        try:
            debut = time.monotonic()
            garde.lit(muet)
            brut = muet.stdout.read(100)
            garde.fini()
            self.assertEqual(brut, b"")
            self.assertLess(time.monotonic() - debut, 5.0)
        finally:
            garde.arrete()
            muet.kill()
            muet.wait(timeout=5)
            muet.stdout.close()

    def test_la_garde_laisse_une_lecture_qui_avance(self):
        vivant = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE)
        garde = stream.GardeEntree(delai_s=0.3, pas_s=0.05)
        try:
            for _ in range(10):
                garde.lit(vivant)
                time.sleep(0.05)
                garde.fini()
            time.sleep(0.5)
            self.assertIsNone(vivant.poll())
        finally:
            garde.arrete()
            vivant.kill()
            vivant.wait(timeout=5)
            vivant.stdout.close()


class RetourVentouxTests(unittest.TestCase):
    def _regarde(self, reponses):
        coupe = threading.Event()
        vif = threading.Event()
        etats = []

        def vive(_url):
            if not reponses:
                coupe.set()
                return False
            return reponses.pop(0)

        def attend(_delai):
            etats.append(vif.is_set())
            return coupe.is_set()

        with mock.patch.object(stream, "_webcam_vive", side_effect=vive), \
                mock.patch.object(coupe, "wait", side_effect=attend):
            stream._regard_le_ventoux("url", coupe, vif, stable=3)
        return etats

    def test_un_seul_regard_sain_ne_rend_pas_l_antenne(self):
        etats = self._regarde([True, False, True, True, False])
        self.assertNotIn(True, etats)

    def test_trois_regards_sains_rendent_l_antenne(self):
        etats = self._regarde([True, True, True])
        self.assertEqual(etats[:3], [False, False, True])


if __name__ == "__main__":
    unittest.main()
