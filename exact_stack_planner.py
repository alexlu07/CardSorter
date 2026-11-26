"""Move records and a validating replay for adjacent top-card transfers."""

from dataclasses import dataclass

NAMES = ("left", "center", "right")
EDGES = ((0, 1), (1, 0), (1, 2), (2, 1))


@dataclass(frozen=True)
class Move:
    card: object
    source: str
    destination: str


def _stacks(stacks):
    result = tuple(tuple(s) for s in stacks)
    if len(result) != 3:
        raise ValueError("Expected left, center, right stacks")
    cards = [c for s in result for c in s]
    if len(set(cards)) != len(cards):
        raise ValueError("Card IDs must be distinct and hashable")
    return result


def apply_moves(stacks, moves, *, protected=(0, 0, 0)):
    stacks = [list(s) for s in _stacks(stacks)]
    if len(protected) != 3 or any(type(n) is not int or not 0 <= n <= len(s)
                                  for n, s in zip(protected, stacks)):
        raise ValueError("Invalid protected bottom-card counts")
    for move in moves:
        source, destination = NAMES.index(move.source), NAMES.index(move.destination)
        if abs(source - destination) != 1:
            raise ValueError("Only adjacent transfers are legal")
        if len(stacks[source]) <= protected[source]:
            raise ValueError("Cannot remove a protected card")
        if stacks[source][0] != move.card:
            raise ValueError("Moved card is not on top")
        stacks[destination].insert(0, stacks[source].pop(0))
    return tuple(tuple(s) for s in stacks)
