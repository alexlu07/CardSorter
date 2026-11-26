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
        """Fresh capture of the stationary top card of the starting compartment; return ID 1..52.

        Reject unreadable/ambiguous images. Do not move the card or reuse a
        cached frame. Recognition is the adapter's responsibility.
        """
        ...

    def move_one(self, source: str, destination: str) -> None:
        """Transfer one top card between adjacent compartments, then stop.

        Return only after sensors confirm delivery and the path is clear. A card
        that lands in the middle must be stationary and exposed for the next scan.
        Raise on uncertainty; the caller will not retry.
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


class ScanDealer:
    """Phase 1: read every card on top of the starting pile and route it by value.

    The camera sees only the top of the starting compartment, so each card is read
    before it moves. combined_sorter.scan_destination decides where it goes; it depends
    only on the card being read. From a side start (hold=True) a card bound for the far
    side moves to the middle and waits there; waiting cards move on only when a card
    bound for the middle is read. Scanning stops once the bottom card is known by
    elimination and it, or the bottom pair, is already in its final place. Mirrors
    combined_sorter.scan_moves exactly. Single use; retains confirmed progress if the
    hardware fails.
    """

    def __init__(self, hardware: Hardware, *, start: str = "left", hold: bool | None = None):
        if start not in ("left", "center", "right"):
            raise ValueError("Start must be left, center, or right")
        self.hardware = hardware
        self.start = start
        self.state = DealState(center=[], left=[], right=[])
        from combined_sorter import SCAN_HOLD

        self.hold = SCAN_HOLD if hold is None else hold
        self.moves: list[tuple[str, str, int]] = []
        self._started = False

    def _physical(self, letter):
        if self.start == "right":
            letter = {"L": "R", "C": "C", "R": "L"}[letter]
        return {"L": "left", "C": "center", "R": "right"}[letter]

    def _move(self, source, destination):
        stacks = {"left": self.state.left, "center": self.state.center, "right": self.state.right}
        self.state.pending_source, self.state.pending_destination = source, destination
        self.hardware.move_one(source, destination)
        card = stacks[source].pop(0) if stacks[source] else None
        if source == self.start:
            self.state.source_remaining -= 1
        stacks[destination].insert(0, card)
        self.state.confirmed_moves += 1
        self.state.pending_source = self.state.pending_destination = None
        return card

    def _route(self, source, destination):
        stacks = {"left": self.state.left, "center": self.state.center, "right": self.state.right}
        self.moves.append((source, destination, stacks[source][0]))
        self._move(source, destination)

    def _read(self, seen):
        self.state.awaiting_scan = True
        value = self.hardware.scan_top()
        card_name(value)  # Validate before enabling any movement.
        if value in seen:
            raise ValueError(f"Duplicate scan: {card_name(value)}")
        seen.add(value)
        self.state.scanned_cards.append(value)
        self.state.awaiting_scan = False
        return value

    def run(self) -> DealState:
        from combined_sorter import scan_destination

        if self._started:
            raise RuntimeError("Dealer already used; reconcile physical stacks before restarting")
        self._started = True
        n = 52
        home = "C" if self.start == "center" else "L"
        seen: set[int] = set()
        try:
            self.hardware.stop()
            getattr(self.state, self.start)[:] = [None] * n  # unread cards, top first
            start_stack = getattr(self.state, self.start)
            far = self._physical("R")
            held = 0  # far-bound cards waiting on the middle (side starts with hold)
            for i in range(n):
                value = self._read(seen)  # the top of the starting pile; nothing has moved
                start_stack[0] = value
                bottom = (set(range(1, n + 1)) - seen).pop() if i == n - 2 else None
                if (i == n - 2 and value == n - 1 and bottom == n) or (i == n - 1 and value == n):
                    start_stack[-1] = bottom if bottom is not None else value
                    break  # the rest is already in its final place
                destination = scan_destination(value, home)
                self.state.pending_card = value
                if home == "C":
                    self._route("center", self._physical(destination))
                elif destination == "C":
                    for _ in range(held):
                        self._route("center", far)
                    held = 0
                    self._route(self.start, "center")
                else:
                    self._route(self.start, "center")
                    if self.hold:
                        held += 1
                    else:
                        self._route("center", far)
                self.state.pending_card = None
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

    def deck(self):
        """The original order, top first, once run() has finished (bottom card by elimination)."""
        missing = sorted(set(range(1, 53)) - set(self.state.scanned_cards))
        return list(self.state.scanned_cards) + missing


class SimulatedHardware:
    """No GPIO or camera access. Input deck is ordered from top to bottom."""

    def __init__(self, deck: list[int], start: str = "left"):
        if len(deck) != 52 or set(deck) != set(range(1, 53)):
            raise ValueError("Simulation requires a complete standard deck")
        if start not in ("left", "center", "right"):
            raise ValueError("Start must be left, center, or right")
        self.start = start
        self.middle = deque(deck if start == "center" else [])
        self.left: list[int] = list(deck) if start == "left" else []
        self.right: list[int] = list(deck) if start == "right" else []
        self.events: list[tuple] = []

    def stop(self) -> None:
        self.events.append(("stop",))

    def scan_top(self) -> int:
        value = {"left": self.left, "center": self.middle, "right": self.right}[self.start][0]
        self.events.append(("scan", value))
        return value

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
                       search_seconds=args.search_seconds).run()
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
            if event[0] == "move":
                print(f"{event[1]} -> {event[2]}: {card_name(event[3])}")
    summary.update(left_top_to_bottom=hardware.left,
                   center_top_to_bottom=list(hardware.middle),
                   right_top_to_bottom=hardware.right)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
