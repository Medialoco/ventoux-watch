"""The Cannes model is a beach and a sea, not a freight yard."""

import unittest

import numpy as np

from scripts.build_cannes_view import REACH, _at_sea, _shores


class CannesViewTests(unittest.TestCase):
    def test_the_beach_is_kept_and_the_freight_yard_is_not(self):
        ring = np.zeros((90, 2), dtype=np.float32)
        ring[:, 0] = np.linspace(0, 80, 90)
        ring[-1] = ring[0]
        yard = np.array([[0, 0], [40, 0], [40, 40], [0, 40], [0, 0]], dtype=np.float32)
        shores = _shores([({"natural": "beach"}, ring), ({"landuse": "railway"}, yard)])
        self.assertEqual([item["k"] for item in shores], ["beach"])
        self.assertEqual(len(shores[0]["p"]), 90)

    def test_the_sea_reaches_the_far_edge(self):
        # The line walks east, so the land is on the left and the sea on the right.
        coast = [np.array([[-400.0, 0.0], [400.0, 0.0]])]
        self.assertTrue(_at_sea(0.0, -300.0, coast, REACH))
        self.assertFalse(_at_sea(0.0, 80.0, coast, REACH))

    def test_a_kink_outside_the_model_does_not_drain_the_sea(self):
        coast = [np.array([[-400.0, 0.0], [400.0, 0.0]])]
        # Closer to the sample than the real shore, and oriented so the sample
        # would count as land. It never enters the model, so it is ignored.
        kink = np.array([[900.0, -360.0], [370.0, -360.0]])
        self.assertTrue(_at_sea(370.0, -370.0, [coast[0], kink], REACH))


if __name__ == "__main__":
    unittest.main()
