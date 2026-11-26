"""Execute the initial scan/deal followed by the complete sorting plan."""

from dataclasses import dataclass
import math

from combined_sorter import BOUND, get_planner
from cards import DealState, Hardware, ScanDealer
from exact_stack_planner import Move, apply_moves
from heuristic_planner import optimize_plan

NAMES = {"L": "left", "C": "center", "R": "right"}


@dataclass(frozen=True)
class SortPlan:
    moves: tuple[Move, ...]
    # End offsets in moves, counted after the scan moves.
    stages: tuple[tuple[str, int], ...]


@dataclass
class SortState:
    initial_deal: DealState
    start: str = "left"
    dealing_stages: tuple[tuple[str, int], ...] = ()
    stacks: tuple | None = None
    phase: str = "1: scan and route"
    plan: SortPlan | None = None
    sorting_moves_confirmed: int = 0
    pending_move: Move | None = None
    completed: bool = False
    fault: str | None = None
    optimization: dict | None = None
    strategy: str = "scan-split"

    @property
    def movements_confirmed(self):
        return self.initial_deal.confirmed_moves + self.sorting_moves_confirmed

    @property
    def movement_budget(self):
        """Certified worst case, scan moves included: 322 from the middle, 350 from a side."""
        return BOUND[self.start[0].upper()]


class CardSorter:
    def __init__(self, hardware: Hardware, *, start: str = "left", optimize: bool = False,
                 search_seconds: float = 2.0):
        if start not in ("left", "center", "right"):
            raise ValueError("Start must be left, center, or right")
        if isinstance(search_seconds, bool) or not isinstance(search_seconds, (int, float)) or not math.isfinite(search_seconds) or not 0 <= search_seconds <= 30:
            raise ValueError("Search time must be between 0 and 30 seconds")
        self.hardware = hardware
        self.optimize = optimize
        self.search_seconds = search_seconds
        self.dealer = ScanDealer(hardware, start=start)
        self.state = SortState(self.dealer.state, start=start)
        self._started = False

    def run(self) -> SortState:
        """Scan and route every card (phase 1), then plan and execute the rest."""
        if self._started:
            raise RuntimeError("Sorter already used; reconcile physical stacks before restarting")
        self._started = True
        try:
            self.state.phase = "1: scan and route"
            deal = self.dealer.run()
            self.state.dealing_stages = ((self.state.phase, deal.confirmed_moves),)
            self.state.phase = "planning"
            # Every card is now known. Plan and verify all remaining moves before moving more.
            deck = self.dealer.deck()
            letter = self.state.start[0].upper()
            route = get_planner().plan_scanned(deck, start=letter)
            head = len(self.dealer.moves)
            if [(NAMES[m.source], NAMES[m.destination], m.card) for m in route[:head]] != self.dealer.moves:
                raise RuntimeError("Planner and scan disagree about the scan moves")
            initial = tuple(tuple(deck) if name == self.state.start else () for name in NAMES.values())
            scan = tuple(Move(m.card, NAMES[m.source], NAMES[m.destination]) for m in route[:head])
            self.state.stacks = apply_moves(initial, scan)
            moves = tuple(Move(m.card, NAMES[m.source], NAMES[m.destination]) for m in route[head:])
            plan = SortPlan(moves, (("2: finish from the scanned layout", len(moves)),))
            expected = [(), (), ()]
            expected[("left", "center", "right").index(self.state.start)] = tuple(range(1, 53))
            if apply_moves(self.state.stacks, plan.moves) != tuple(expected):
                raise RuntimeError("Plan does not finish sorted in its starting compartment")
            if self.state.initial_deal.confirmed_moves + len(plan.moves) > self.state.movement_budget:
                raise RuntimeError("Plan exceeds its movement budget")
            if self.optimize:
                label = "Beam search"
                self.state.phase = f"{label}: improving remaining plan"
                result = optimize_plan(self.state.stacks, tuple(expected), plan.moves,
                                       seconds=self.search_seconds)
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
