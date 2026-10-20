"""Checks that the animation catalogue matches the APK's reachable lists."""

from __future__ import annotations

import unittest

from mrstar.modes import CATEGORIES, CATEGORY_BY_NAME, find_mode


class ModeCatalogueTests(unittest.TestCase):
    def test_category_sizes(self) -> None:
        expected = {
            "Basic": 12,
            "Opening & closing": 10,
            "Transition": 10,
            "Running water": 8,
            "Tailing": 8,
            "Running": 10,
            "Flow": 13,
        }
        self.assertEqual(
            {category.name: len(category.modes) for category in CATEGORIES},
            expected,
        )

    def test_ids_are_unique(self) -> None:
        ids = [ident for category in CATEGORIES for ident, _label in category.modes]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 71)

    def test_known_ids(self) -> None:
        flow = CATEGORY_BY_NAME["Flow"]
        self.assertTrue(flow.hidden)
        self.assertEqual(tuple(ident for ident, _ in flow.modes), tuple(range(63, 76)))

        basic = CATEGORY_BY_NAME["Basic"]
        self.assertEqual(
            tuple(ident for ident, _ in basic.modes),
            (1, 2, 3, 4, 7, 10, 26, 27, 29, 30, 31, 32),
        )
        self.assertEqual(
            tuple(ident for ident, _ in CATEGORY_BY_NAME["Running"].modes),
            tuple(range(84, 94)),
        )

    def test_labels(self) -> None:
        self.assertEqual(find_mode(1), (CATEGORY_BY_NAME["Basic"], "Automatic loop"))
        self.assertEqual(find_mode(2)[1], "Symphony")
        self.assertEqual(find_mode(63)[1], "Black-white running water")
        self.assertIsNone(find_mode(94))

    def test_no_empty_labels(self) -> None:
        for category in CATEGORIES:
            self.assertTrue(category.name)
            for ident, label in category.modes:
                self.assertGreaterEqual(ident, 1)
                self.assertTrue(label.strip(), f"mode {ident} has no label")


if __name__ == "__main__":
    unittest.main()
