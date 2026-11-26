"""Hardware contract, card names, and a simulator.

Hardware methods use compartment names ('left', 'center', 'right'); model.NAMES maps the
planner's letters to them.
"""

from __future__ import annotations

from collections import deque
from typing import Protocol

from .model import NAMES

RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUITS = ("clubs", "diamonds", "hearts", "spades")
COMPARTMENTS = tuple(NAMES.values())


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

        Return only after sensors confirm delivery and the path is clear.
        Raise on uncertainty; the caller will not retry.
        """
        ...


class SimulatedHardware:
    """No GPIO or camera access. Input deck is ordered from top to bottom.

    `events` records ("scan", card), ("move", source, destination, card) and ("stop",).
    """

    def __init__(self, deck: list[int], start: str = "left"):
        if len(deck) != 52 or set(deck) != set(range(1, 53)):
            raise ValueError("Simulation requires a complete standard deck")
        if start not in COMPARTMENTS:
            raise ValueError("Start must be left, center, or right")
        self.start = start
        self.stacks = {name: deque(deck if name == start else []) for name in COMPARTMENTS}
        self.events: list[tuple] = []

    @property
    def left(self):
        return list(self.stacks["left"])

    @property
    def middle(self):
        return list(self.stacks["center"])

    @property
    def right(self):
        return list(self.stacks["right"])

    def stop(self) -> None:
        self.events.append(("stop",))

    def scan_top(self) -> int:
        value = self.stacks[self.start][0]
        self.events.append(("scan", value))
        return value

    def move_one(self, source: str, destination: str) -> None:
        if abs(COMPARTMENTS.index(source) - COMPARTMENTS.index(destination)) != 1:
            raise ValueError("Only adjacent transfers are legal")
        value = self.stacks[source].popleft()
        self.stacks[destination].appendleft(value)
        self.events.append(("move", source, destination, value))
