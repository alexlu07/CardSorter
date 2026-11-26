"""Execute the initial scan/deal followed by the complete sorting plan."""

from dataclasses import dataclass
import math
from typing import Protocol

from card_sorter import bounds
from combined_sorter import plan as plan_deck
from cards import DealState, Hardware, InitialDealer, SideDealer
from card_sort_planner import SortPlan, plan_remaining, plan_side_remaining, side_movement_budget
from exact_stack_planner import Move, apply_moves
from heuristic_planner import optimize_plan


class SortingHardware(Hardware, Protocol):
    def move_one(self, source: str, destination: str) -> None:
        """Transfer one top card along an adjacent path, then stop.

        Same delivery confirmation, single-feed, and bounded timeout requirements
        as transfer_one(). Both directions must be supported on each path.
        Raise on uncertainty; the caller will not retry.
        """
        ...


@dataclass
class SortState:
    initial_deal: DealState
    start: str = "left"
    dealing_stages: tuple[tuple[str, int], ...] = ()
    stacks: tuple | None = None
    phase: str = "1: scan and distribute"
    plan: SortPlan | None = None
    sorting_moves_confirmed: int = 0
    pending_move: Move | None = None
    completed: bool = False
    fault: str | None = None
    optimization: dict | None = None

    prescanned: bool = False

    @property
    def movements_confirmed(self):
        return self.initial_deal.confirmed_moves + self.sorting_moves_confirmed

    @property
    def movement_budget(self):
        if self.prescanned:
            return bounds(start=self.start[0].upper())[0]
        return 350 if self.start == "center" else side_movement_budget()

    @property
    def strategy(self):
        if self.prescanned:
            return "prescanned-combined"
        return "middle-partition-and-merge" if self.start == "center" else "direct-side"


class CardSorter:
    def __init__(self, hardware: SortingHardware, *, start: str = "left", optimize: bool = False,
                 search_seconds: float = 2.0, search_algorithm: str = "beam"):
        if start not in ("left", "center", "right"):
            raise ValueError("Start must be left, center, or right")
        if isinstance(search_seconds, bool) or not isinstance(search_seconds, (int, float)) or not math.isfinite(search_seconds) or not 0 <= search_seconds <= 30:
            raise ValueError("Search time must be between 0 and 30 seconds")
        if search_algorithm not in ("beam", "astar", "ida"):
            raise ValueError("Search algorithm must be beam, astar, or ida")
        self.hardware = hardware
        self.optimize = optimize
        self.search_seconds = search_seconds
        self.search_algorithm = search_algorithm
        self.dealer = InitialDealer(hardware) if start == "center" else SideDealer(hardware, start=start)
        self.state = SortState(self.dealer.state, start=start)
        self._started = False

    def run(self, *, deck=None) -> SortState:
        if self._started:
            raise RuntimeError("Sorter already used; reconcile physical stacks before restarting")
        self._started = True
        try:
            if deck is None:
                self.state.phase = "1: scan and distribute" if self.state.start == "center" else "1: feed through camera and partition"
                deal = self.dealer.run()
                self.state.dealing_stages = ((self.state.phase, deal.confirmed_moves),)
                self.state.stacks = (tuple(deal.left), tuple(deal.center), tuple(deal.right))
                self.state.phase = "planning"
                # Plan and verify every remaining move before operating more motors.
                if self.state.start == "center":
                    plan = plan_remaining(deal.left, deal.right)
                else:
                    opposite = deal.right if self.state.start == "left" else deal.left
                    plan = plan_side_remaining(deal.center, opposite, start=self.state.start)
            else:
                cards = tuple(deck)
                if len(cards) != 52:
                    raise ValueError("Hardware execution requires 52 cards")
                self.state.prescanned = True
                self.state.phase = "planning"
                names = {"L": "left", "C": "center", "R": "right"}
                route = plan_deck(cards, start=self.state.start[0].upper())
                moves = tuple(Move(card, names[src], names[dst]) for src, dst, card in route)
                plan = SortPlan(moves, (("Sort scanned deck", len(moves)),))
                self.state.stacks = tuple(cards if name == self.state.start else () for name in names.values())
            expected = [(), (), ()]
            expected[("left", "center", "right").index(self.state.start)] = tuple(range(1, 53))
            if apply_moves(self.state.stacks, plan.moves) != tuple(expected):
                raise RuntimeError("Plan does not finish sorted in its starting compartment")
            if self.state.initial_deal.confirmed_moves + len(plan.moves) > self.state.movement_budget:
                raise RuntimeError("Plan exceeds its movement budget")
            if self.optimize:
                label = {"beam": "Beam search", "astar": "A*", "ida": "IDA*"}[self.search_algorithm]
                self.state.phase = f"{label}: improving remaining plan"
                result = optimize_plan(self.state.stacks, tuple(expected), plan.moves,
                                       seconds=self.search_seconds, algorithm=self.search_algorithm)
                self.state.optimization = result.summary()
                if result.moves != plan.moves:
                    plan = SortPlan(result.moves, ((f"{label}: execute improved plan", len(result.moves)),))
            self.state.plan = plan
            for index, move in enumerate(plan.moves):
                self.state.phase = next(name for name, end in plan.stages if index < end)
                next_stacks = apply_moves(self.state.stacks, [move])
                self.state.pending_move = move
                self.hardware.move_one(move.source, move.destination)
                self.state.stacks = next_stacks
                self.state.sorting_moves_confirmed += 1
                self.state.pending_move = None
            self.hardware.stop()
            self.state.phase = "complete"
            self.state.completed = True
            return self.state
        except BaseException as error:
            self.state.fault = f"{type(error).__name__}: {error}"
            try:
                self.hardware.stop()
            except BaseException as stop_error:
                self.state.fault += f"; stop also failed: {stop_error}"
            raise
