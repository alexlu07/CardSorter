"""Regression tests: python -m unittest discover tests

golden.json holds the exact move lists (hashed) produced before the package restructure, for
a fixed set of decks and all three starts. Every planner and the simulated hardware must
reproduce them move for move. By default a representative subset runs (about two minutes);
set CARDSORTER_FULL=1 to check every recorded case.
"""

import hashlib
import json
import os
import unittest
from pathlib import Path

from cardsorter import model, scan, strategy_a
from cardsorter.controller import CardSorter
from cardsorter.hardware import SimulatedHardware
from cardsorter.improver import optimize_plan
from cardsorter.planner import BOUND, get_planner

GOLDEN = json.loads((Path(__file__).with_name("golden.json")).read_text(encoding="utf-8"))
QUICK = ["seed0/C", "seed0/L", "seed1/R", "sorted/C", "sorted/L", "reversed/R", "bottom52/C",
         "bottom52/L", "n5/C", "n12/L", "n20/R"]
CASES = sorted(GOLDEN["plans"]) if os.environ.get("CARDSORTER_FULL") else QUICK
NAMES = {"C": "center", "L": "left", "R": "right"}


def digest(items):
    return hashlib.sha256("|".join(map(str, items)).encode()).hexdigest()[:16]


def record(moves):
    return {"len": len(moves), "sha": digest(f"{m.source}{m.destination}{m.card}" for m in moves)}


class GoldenPlans(unittest.TestCase):
    """Same moves as before the refactor, and every plan verifies and meets its bound."""

    @classmethod
    def setUpClass(cls):
        cls.planner = get_planner()

    def check(self, key, kind, moves, deck, start):
        self.assertEqual(record(moves), GOLDEN["plans"][key][kind], f"{key} {kind}")
        self.assertEqual(model.verify(deck, moves, start=start), len(moves))
        if len(deck) == 52:
            self.assertLessEqual(len(moves), BOUND[start])

    def test_plans(self):
        for key in CASES:
            name, start = key.split("/")
            deck = GOLDEN["decks"][name]
            with self.subTest(key):
                self.check(key, "A", strategy_a.plan(deck, start=start), deck, start)
                self.check(key, "full", self.planner.plan(deck, start), deck, start)
                self.check(key, "scan", self.planner.plan_scanned(deck, start), deck, start)
                self.check(key, "scan_eager", self.planner.plan_scanned(deck, start, hold=False), deck, start)

    def test_hardware(self):
        for key in CASES:
            name, start = key.split("/")
            deck = GOLDEN["decks"][name]
            if len(deck) != 52:
                continue
            with self.subTest(key):
                hardware = SimulatedHardware(deck, start=NAMES[start])
                state = CardSorter(hardware, start=NAMES[start]).run()
                events = [e for e in hardware.events if e[0] != "stop"]
                got = {"movements": state.movements_confirmed, "sha": digest(events),
                       "scans": sum(e[0] == "scan" for e in events)}
                self.assertEqual(got, GOLDEN["plans"][key]["hardware"])
                self.assertTrue(state.completed)
                self.assertEqual(hardware.stacks[NAMES[start]], type(hardware.stacks[NAMES[start]])(range(1, 53)))


class Bounds(unittest.TestCase):
    def test_strategy_a_bounds(self):
        for start, (worst, mean) in GOLDEN["bounds"].items():
            got = strategy_a.bounds(52, start=start)
            self.assertEqual([got[0], str(got[1])], [worst, mean])

    def test_scan_bound(self):
        for home, worst in GOLDEN["scan_bound"].items():
            self.assertEqual(scan.scan_bound(52, home), worst)
            self.assertEqual(worst, BOUND[home])

    def test_scan_moves(self):
        for key, moves in GOLDEN["scan_moves"].items():
            name, home, hold = key.split("/")
            got = scan.scan_moves(GOLDEN["decks"][name], home, None, hold == "True")[0]
            self.assertEqual([list(m) for m in got], moves, key)

    def test_reversed_deck_is_exact(self):
        deck = list(range(52, 0, -1))
        self.assertEqual(len(get_planner().plan_scanned(deck, "C")), 4 * 51)
        self.assertEqual(len(get_planner().plan_scanned(deck, "L")), 4 * 52 - 2)


class Model(unittest.TestCase):
    def test_letters(self):
        self.assertEqual([model.letter(x) for x in ("L", "left", "center", "middle", "R")],
                         ["L", "L", "C", "C", "R"])
        with self.assertRaises(ValueError):
            model.letter("top")

    def test_apply_moves_rejects_illegal(self):
        stacks = ((1, 2), (), ())
        with self.assertRaises(ValueError):
            model.apply_moves(stacks, [model.Move("L", "R", 1)])  # not adjacent
        with self.assertRaises(ValueError):
            model.apply_moves(stacks, [model.Move("L", "C", 2)])  # not on top
        with self.assertRaises(ValueError):
            model.apply_moves(stacks, [model.Move("L", "C", 1)], protected=(2, 0, 0))

    def test_verify_rejects_unsorted(self):
        with self.assertRaises(ValueError):
            model.verify([2, 1], [model.Move("C", "L", 2)], start="C")

    def test_time_reversal_sorts_the_inverse(self):
        deck = [3, 1, 4, 2, 5]
        pairs = [(m.source, m.destination) for m in strategy_a.plan(deck, start="C")]
        self.assertTrue(model.sorts(model.inverse(deck), model.time_reverse(pairs), "C"))


class Improver(unittest.TestCase):
    def test_never_longer_and_valid(self):
        deck = GOLDEN["decks"]["seed3"]
        moves = get_planner().plan_scanned(deck, "C")
        initial = ((), tuple(deck), ())
        target = ((), tuple(range(1, 53)), ())
        result = optimize_plan(initial, target, moves, seconds=0.5)
        self.assertLessEqual(len(result.moves), len(moves))
        self.assertEqual(model.apply_moves(initial, result.moves), target)


class Visualizer(unittest.TestCase):
    def test_simulation_payload(self):
        from cardsorter.visualizer import simulation
        payload = simulation(5, start="center")
        moves = [e for e in payload["events"] if e["kind"] == "move"]
        self.assertEqual(len(moves), payload["movements"])
        self.assertLessEqual(payload["movements"], payload["movement_budget"])
        self.assertGreaterEqual(payload["scans"], 51)


if __name__ == "__main__":
    unittest.main()
