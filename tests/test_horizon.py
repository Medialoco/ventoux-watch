"""Le calage sur l'horizon : une fourchette physique, pas un réglage de cadre."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts import build_crete, cale_horizon
from watcher.stream import fenetre


class FourchetteTests(unittest.TestCase):
    """Le sol nu ne peut pas se voir plus haut que ce qui s'y dresse."""

    def test_the_canopy_always_sits_above_bare_ground(self):
        """Vingt mètres de pins montent l'horizon ; rien ne le descend."""
        self.assertEqual(cale_horizon.CANOPEE_M, 20.0)
        # Un sol plat sous l'œil : plus loin, plus bas. Avec une canopée,
        # le même point se voit plus haut.
        n = 21
        sol = np.full((n, n), -40.0)
        relief = cale_horizon.Relief(
            {"step_m": 20.0, "reach_m": 200.0, "grid": sol.tolist()})
        nu = relief.horizon(0.0, 0.0)
        haut = relief.horizon(0.0, cale_horizon.CANOPEE_M)
        self.assertIsNotNone(nu)
        self.assertIsNotNone(haut)
        self.assertGreater(haut[0], nu[0])

    def test_the_nearest_steepest_angle_hides_what_is_behind(self):
        """Une butte proche cache un sommet plus loin et plus bas en angle."""
        n = 21
        sol = np.full((n, n), -80.0)
        # Au nord, à 140 m — au-delà de DEPART_M : une butte qui monte à l'œil.
        sol[3, 10] = 40.0
        relief = cale_horizon.Relief(
            {"step_m": 20.0, "reach_m": 200.0, "grid": sol.tolist()})
        angle, loin = relief.horizon(0.0)
        self.assertLess(loin, 180.0)
        self.assertGreater(angle, 0.0)


class PansTests(unittest.TestCase):
    """On ne trace que ce que l'image confirme."""

    def test_a_denied_bearing_cuts_the_line(self):
        """Là où le sol calculé sort de la fourchette, le trait s'arrête."""
        points = [(0.1, 0.4, True), (0.2, 0.41, True), (0.3, 0.42, False),
                  (0.4, 0.43, True), (0.5, 0.44, True)]
        traits = build_crete.pans(points)
        self.assertEqual(len(traits), 2)
        self.assertEqual(traits[0][0][0], 0.1)
        self.assertEqual(traits[1][0][0], 0.4)

    def test_outside_the_frame_only_extends_a_confirmed_span(self):
        """Une bande noire n'invente pas une crête. Elle prolonge."""
        self.assertEqual(build_crete.pans([(0.0, 0.4, None), (0.1, 0.4, None)]), [])
        traits = build_crete.pans([(0.2, 0.4, True), (0.3, 0.4, True),
                                  (1.05, 0.4, None), (1.10, 0.4, None)])
        self.assertEqual(len(traits), 1)
        self.assertGreater(traits[0][-1][0], 1.0)

    def test_a_short_scratch_is_not_a_ridge(self):
        """Moins de cinq pour cent de la toile, c'est une rayure."""
        points = [(0.40, 0.4, True), (0.42, 0.4, True)]
        self.assertEqual(build_crete.pans(points), [])


class ToileTests(unittest.TestCase):
    """Les bandes noires viennent de la fenêtre, pas d'un cadrage du Ventoux."""

    def test_the_letterbox_is_the_window_and_nothing_else(self):
        gauche, droite, haut, bas = build_crete.toile_en_camera()
        x, y, large, haute = fenetre(build_crete.TOILE_CAM, *build_crete.TOILE_REF)
        self.assertAlmostEqual(gauche, -x / large, places=6)
        self.assertAlmostEqual(droite, (build_crete.TOILE_REF[0] - x) / large, places=6)
        self.assertAlmostEqual(haut, -y / haute, places=6)
        self.assertAlmostEqual(bas, (build_crete.TOILE_REF[1] - y) / haute, places=6)
        # L'image elle-même est bien dans ]0, 1[.
        self.assertLess(gauche, 0.0)
        self.assertGreater(droite, 1.0)


class ReleveTests(unittest.TestCase):
    """La crête dans l'image est la première chute sous le ciel."""

    def test_the_ridge_is_the_first_drop_under_the_sky(self):
        image = np.full((100, 80, 3), 200, np.uint8)
        image[40:, :] = 40
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "ciel.jpg"
            cv2.imwrite(str(chemin), image)
            vu = cale_horizon.releve_image([chemin])
        self.assertEqual(len(vu), 80)
        self.assertTrue(np.all(np.abs(vu - 0.40) < 0.02))

    def test_a_thin_wire_is_not_the_ridge(self):
        """Un fil, un flare : trop mince pour un versant."""
        image = np.full((100, 40, 3), 200, np.uint8)
        image[20, :] = 10
        image[50:, :] = 40
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "fil.jpg"
            cv2.imwrite(str(chemin), image)
            vu = cale_horizon.releve_image([chemin])
        self.assertTrue(np.all(np.abs(vu - 0.50) < 0.03))


class PoseEcriteTests(unittest.TestCase):
    """Sans écriture, caler ne sert à rien."""

    def test_writing_the_pose_is_an_explicit_choice(self):
        source = Path(cale_horizon.__file__).read_text(encoding="utf-8")
        self.assertIn("--ecrit", source)
        self.assertIn("def ecrit_pose(", source)
        # Et on n'écrit pas si le coût n'a pas baissé.
        self.assertIn("apres >= avant", source)


if __name__ == "__main__":
    unittest.main()
