"""Three-compartment card sorter. Run with --demo for simulated hardware only."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import json
import random
from typing import Protocol


class Side(str, Enum):
    LEFT = "left"
    RIGHT = "right"


RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUITS = ("clubs", "diamonds", "hearts", "spades")


def card_id(rank: str, suit: str) -> int:
    """A clubs=1, K clubs=13, A diamonds=14, ..., K spades=52."""
    return SUITS.index(suit.lower()) * 13 + RANKS.index(rank.upper()) + 1


def card_name(value: int) -> str:
    if type(value) is not int or not 1 <= value <= 52:
        raise ValueError("Card ID must be an integer from 1 to 52")
    suit, rank = divmod(value - 1, 13)
    return f"{RANKS[rank]} of {SUITS[suit]}"


class Hardware(Protocol):
    """Adapter contract; all blocking operations MUST have hardware timeouts.

    Real adapters must raise on jams, missing cards, double feeds, or timeouts.
    Never infer successful delivery solely from elapsed time or encoder counts.
    """

    def stop(self) -> None:
        """Stop all rollers. Must also work after a transfer failure."""
        ...

    def scan_top(self) -> int:
        """Fresh capture of the stationary middle top card; return ID 1..52.

        Reject unreadable/ambiguous images. Do not move the card or reuse a
        cached frame. Recognition is the adapter's responsibility.
        """
        ...

    def transfer_one(self, destination: Side) -> None:
        """Move exactly one middle card to an adjacent stack, then stop.

        Return only after sensors confirm delivery and the path is clear.
        The next card must be stationary and exposed for the next scan.
        """
        ...


@dataclass
class DealState:
    # Lists describe physical stacks from TOP to BOTTOM. New cards land on top.
    left: list[int] = field(default_factory=list)
    right: list[int] = field(default_factory=list)
    center: list[int] = field(default_factory=list)
    source_remaining: int = 52
    confirmed_moves: int = 0
    scanned_cards: list[int] = field(default_factory=list)
    awaiting_scan: bool = False
    completed: bool = False
    fault: str | None = None
    pending_card: int | None = None
    pending_source: str | None = None
    pending_destination: str | None = None

    @property
    def middle_remaining(self):
        """Legacy scan-feed count; use source_remaining for selectable starts."""
        return self.source_remaining


class InitialDealer:
    """Single-use controller. Retains confirmed progress if hardware fails."""

    def __init__(self, hardware: Hardware, *, descending: bool = False):
        self.hardware = hardware
        self.descending = descending
        self.state = DealState()
        self._started = False

    def run(self) -> DealState:
        if self._started:
            raise RuntimeError("Controller already used; reconcile physical stacks before restarting")
        self._started = True
        seen: set[int] = set()
        try:
            self.hardware.stop()
            for _ in range(52):
                value = self.hardware.scan_top()
                card_name(value)  # Validate before enabling any movement.
                if value in seen:
                    raise ValueError(f"Duplicate scan: {card_name(value)}")
                self.state.scanned_cards.append(value)
                # Plan in reversed value order when returning to a side stack.
                sort_value = 53 - value if self.descending else value
                destination = Side.LEFT if sort_value >= 33 else Side.RIGHT
                self.state.pending_card = value
                self.state.pending_source = "center"
                self.state.pending_destination = destination.value
                self.hardware.transfer_one(destination)
                stack = self.state.left if destination is Side.LEFT else self.state.right
                stack.insert(0, value)
                seen.add(value)
                self.state.source_remaining -= 1
                self.state.confirmed_moves += 1
                self.state.pending_card = None
                self.state.pending_source = None
                self.state.pending_destination = None
            self.hardware.stop()
            self.state.completed = True
            return self.state
        except BaseException as error:
            self.state.fault = f"{type(error).__name__}: {error}"
            try:
                self.hardware.stop()
            except BaseException as stop_error:
                self.state.fault += f"; stop also failed: {stop_error}"
            raise


class SideDealer:
    """Feed side cards through the middle camera as part of the actual partition.

    Unknown source cards are represented by source_remaining, not by a guessed
    identity. There is never a whole-deck center staging pass.
    """

    def __init__(self, hardware, *, start="left"):
        from card_sort_planner import side_prefix_size

        if start not in ("left", "right"):
            raise ValueError("Side dealer requires left or right")
        self.hardware = hardware
        self.start = start
        self.opposite = "right" if start == "left" else "left"
        self.prefix_size = side_prefix_size()
        self.state = DealState()
        self._started = False

    def run(self):
        if self._started:
            raise RuntimeError("Dealer already used; reconcile physical stacks before restarting")
        self._started = True
        seen = set()
        try:
            self.hardware.stop()
            for _ in range(52):
                self.state.pending_source = self.start
                self.state.pending_destination = "center"
                self.hardware.move_one(self.start, "center")
                self.state.source_remaining -= 1
                self.state.confirmed_moves += 1
                self.state.pending_source = None
                self.state.pending_destination = None
                self.state.awaiting_scan = True
                value = self.hardware.scan_top()
                card_name(value)
                if value in seen:
                    raise ValueError(f"Duplicate scan: {card_name(value)}")
                seen.add(value)
                self.state.scanned_cards.append(value)
                self.state.center.insert(0, value)
                self.state.awaiting_scan = False
                if value <= self.prefix_size:
                    self.state.pending_card = value
                    self.state.pending_source = "center"
                    self.state.pending_destination = self.opposite
                    self.hardware.move_one("center", self.opposite)
                    self.state.confirmed_moves += 1
                    self.state.center.pop(0)
                    getattr(self.state, self.opposite).insert(0, value)
                    self.state.pending_card = None
                    self.state.pending_source = None
                    self.state.pending_destination = None
            self.hardware.stop()
            self.state.completed = True
            return self.state
        except BaseException as error:
            self.state.fault = f"{type(error).__name__}: {error}"
            try:
                self.hardware.stop()
            except BaseException as stop_error:
                self.state.fault += f"; stop also failed: {stop_error}"
            raise


class SimulatedHardware:
    """No GPIO or camera access. Input deck is ordered from top to bottom."""

    def __init__(self, deck: list[int], start: str = "left"):
        if len(deck) != 52 or set(deck) != set(range(1, 53)):
            raise ValueError("Simulation requires a complete standard deck")
        if start not in ("left", "center", "right"):
            raise ValueError("Start must be left, center, or right")
        self.middle = deque(deck if start == "center" else [])
        self.left: list[int] = list(deck) if start == "left" else []
        self.right: list[int] = list(deck) if start == "right" else []
        self.events: list[tuple] = []

    def stop(self) -> None:
        self.events.append(("stop",))

    def scan_top(self) -> int:
        value = self.middle[0]
        self.events.append(("scan", value))
        return value

    def transfer_one(self, destination: Side) -> None:
        value = self.middle.popleft()
        stack = self.left if destination == Side.LEFT else self.right
        stack.insert(0, value)
        self.events.append(("transfer", destination.value, value))

    def move_one(self, source: str, destination: str) -> None:
        names = ("left", "center", "right")
        if abs(names.index(source) - names.index(destination)) != 1:
            raise ValueError("Only adjacent transfers are legal")
        stacks = {"left": self.left, "center": self.middle, "right": self.right}
        origin, target = stacks[source], stacks[destination]
        value = origin.popleft() if source == "center" else origin.pop(0)
        if destination == "center":
            target.appendleft(value)
        else:
            target.insert(0, value)
        self.events.append(("move", source, destination, value))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="run without physical hardware")
    parser.add_argument("--seed", type=int, default=42, help="repeatable shuffled demo deck")
    parser.add_argument("--start", choices=("left", "center", "right"), default="left",
                        help="starting and finishing compartment (default: left)")
    parser.add_argument("--show-moves", action="store_true", help="print each confirmed adjacent transfer")
    parser.add_argument("--optimize", action="store_true", help="search for fewer moves after scanning")
    parser.add_argument("--search-algorithm", choices=("beam", "astar", "ida"), default="beam",
                        help="optimizer algorithm (default: beam)")
    parser.add_argument("--search-seconds", type=float, default=2.0,
                        help="optimizer search budget, 0–30 seconds (default: 2)")
    args = parser.parse_args()
    if not args.demo:
        parser.error("Use --demo. Physical motor/camera adapters are not implemented yet.")
    deck = list(range(1, 53))
    random.Random(args.seed).shuffle(deck)
    hardware = SimulatedHardware(deck, start=args.start)
    from sorter import CardSorter

    state = CardSorter(hardware, start=args.start, optimize=args.optimize,
                       search_seconds=args.search_seconds, search_algorithm=args.search_algorithm).run()
    start = 0
    stages = {}
    previous = 0
    for name, end in state.dealing_stages:
        stages[name] = end - previous
        previous = end
    for name, end in state.plan.stages:
        stages[name] = end - start
        start = end
    summary = {"completed": state.completed, "movements": state.movements_confirmed,
               "start": args.start, "finish": args.start,
               "movement_budget": state.movement_budget, "strategy": state.strategy,
               "stage_movements": stages}
    if state.optimization is not None:
        summary["optimization"] = state.optimization
    if args.show_moves:
        for event in hardware.events:
            if event[0] == "transfer":
                print(f"center -> {event[1]}: {card_name(event[2])}")
            elif event[0] == "move":
                print(f"{event[1]} -> {event[2]}: {card_name(event[3])}")
    summary.update(left_top_to_bottom=hardware.left,
                   center_top_to_bottom=list(hardware.middle),
                   right_top_to_bottom=hardware.right)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
