"""Cannes ne doit pas réveiller un fil par cœur."""

import inspect
import unittest

from watcher import stream
from watcher.main import _frames


class ChargeCannesTests(unittest.TestCase):
    def test_cannes_est_bornee(self):
        self.assertEqual(stream.FILS_CANNES, 1)
        self.assertEqual(stream.CADENCE_CANNES, 2)
        self.assertEqual(stream.FILS_ENTREE, 2)
        self.assertEqual(stream.FILS_SORTIE, 2)
        cadre = inspect.getsource(stream._entree_cadre)
        self.assertIn('"-threads", str(fils)', cadre)
        self.assertLess(cadre.index('"-threads"'), cadre.index('"-i", url'))
        entree = inspect.getsource(stream._entree)
        self.assertIn("FILS_ENTREE", entree)
        sortie = inspect.getsource(stream._sortie)
        self.assertIn("FILS_SORTIE", sortie)
        diffuse = inspect.getsource(stream.diffuse)
        self.assertIn("Compagne(cfg, CADENCE_CANNES)", diffuse)
        self.assertIn("setNumThreads(FILS_ENTREE)", diffuse)
        secours = inspect.getsource(stream._ouvre_secours)
        self.assertIn("FILS_ENTREE", secours)
        horloge, mont = inspect.getsource(_frames).split("if horloge:", 1)[1].split("else:", 1)
        self.assertIn('"-threads", "1"', horloge)
        self.assertIn('"-threads", "1"', mont)


if __name__ == "__main__":
    unittest.main()
