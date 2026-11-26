"""Phase 1 on the hardware: read every card on the starting pile and route it by value."""

from __future__ import annotations

from dataclasses import dataclass, field

from .hardware import Hardware, card_name
from .model import MIRROR, NAMES
from .scan import SCAN_HOLD, scan_destination


@dataclass
class DealState:
    # Lists describe physical stacks from TOP to BOTTOM; unread cards are None.
    left: list = field(default_factory=list)
    right: list = field(default_factory=list)
    center: list = field(default_factory=list)
    source_remaining: int = 52
    confirmed_moves: int = 0
    scanned_cards: list[int] = field(default_factory=list)
    awaiting_scan: bool = False
    completed: bool = False
    fault: str | None = None
    pending_card: int | None = None
    pending_source: str | None = None
    pending_destination: str | None = None


class ScanDealer:
    """Read each card on top of the starting pile, then route it with scan.scan_destination.

    The decision uses only the card being read. From a side start with hold, a card bound
    for the far side moves to the middle and waits there; waiting cards move on only when a
    card bound for the middle is read. Scanning stops once the bottom card is known by
    elimination and it, or the bottom pair, is already in place. This mirrors
    scan.scan_moves exactly. Single use; retains confirmed progress if the hardware fails.
    """

    def __init__(self, hardware: Hardware, *, start: str = "left", hold: bool | None = None):
        if start not in NAMES.values():
            raise ValueError("Start must be left, center, or right")
        self.hardware = hardware
        self.start = start
        self.hold = SCAN_HOLD if hold is None else hold
        self.state = DealState()
        self.moves: list[tuple[str, str, int]] = []  # (source, destination, card), names
        self._started = False

    def _physical(self, stack):
        """Planner letter (planned as if starting on C or L) -> compartment name."""
        if self.start == "right":
            stack = MIRROR[stack]
        return NAMES[stack]

    def _stack(self, name):
        return getattr(self.state, name)

    def _route(self, source, destination):
        card = self._stack(source)[0]
        self.moves.append((source, destination, card))
        self.state.pending_source, self.state.pending_destination = source, destination
        self.hardware.move_one(source, destination)
        self._stack(source).pop(0)
        if source == self.start:
            self.state.source_remaining -= 1
        self._stack(destination).insert(0, card)
        self.state.confirmed_moves += 1
        self.state.pending_source = self.state.pending_destination = None

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
        if self._started:
            raise RuntimeError("Dealer already used; reconcile physical stacks before restarting")
        self._started = True
        n = 52
        home = "C" if self.start == "center" else "L"
        seen: set[int] = set()
        try:
            self.hardware.stop()
            start_stack = self._stack(self.start)
            start_stack[:] = [None] * n
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
