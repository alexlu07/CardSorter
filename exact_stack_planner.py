"""Shortest adjacent top-card plans for at most eight distinct active cards."""

from dataclasses import dataclass
from functools import lru_cache

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


def _neighbors(state):
    stacks = state.split(b"\0")
    for source, destination in EDGES:
        if stacks[source]:
            next_stacks = stacks.copy()
            next_stacks[source] = stacks[source][1:]
            next_stacks[destination] = stacks[source][:1] + stacks[destination]
            yield b"\0".join(next_stacks)


@lru_cache(maxsize=128)
def _path(initial, target):
    if initial == target:
        return (initial,)
    forward, backward = {initial: None}, {target: None}
    front, back = [initial], [target]
    meeting = None
    while meeting is None:
        # Expand a complete BFS depth layer from the smaller frontier.
        own, other, layer = (forward, backward, front) if len(front) <= len(back) else (backward, forward, back)
        next_layer = []
        for state in layer:
            for neighbor in _neighbors(state):
                if neighbor in own:
                    continue
                own[neighbor] = state
                next_layer.append(neighbor)
                if neighbor in other:
                    meeting = neighbor
                    break
            if meeting is not None:
                break
        if not next_layer:
            raise ValueError("No legal path")
        if own is forward:
            front = next_layer
        else:
            back = next_layer
    prefix = []
    state = meeting
    while state is not None:
        prefix.append(state)
        state = forward[state]
    path = prefix[::-1]
    state = backward[meeting]
    while state is not None:
        path.append(state)
        state = backward[state]
    return tuple(path)


def exact_plan(initial, target):
    initial, target = _stacks(initial), _stacks(target)
    labels = tuple(c for stack in initial for c in stack)
    if len(labels) > 8:
        raise ValueError("Exact search supports at most eight active cards total")
    if set(labels) != {c for stack in target for c in stack}:
        raise ValueError("Initial and target cards must match")
    ids = {card: i + 1 for i, card in enumerate(labels)}

    def encode(stacks):
        return b"\0".join(bytes(ids[c] for c in stack) for stack in stacks)

    path = _path(encode(initial), encode(target))
    moves = []
    for before, after in zip(path, path[1:]):
        a, b = before.split(b"\0"), after.split(b"\0")
        source = next(i for i in range(3) if len(a[i]) > len(b[i]))
        destination = next(i for i in range(3) if len(a[i]) < len(b[i]))
        moves.append(Move(labels[a[source][0] - 1], NAMES[source], NAMES[destination]))
    return moves


def plan_block(cards, *, source, destination, order):
    initial, target = [(), (), ()], [(), (), ()]
    initial[NAMES.index(source)] = tuple(cards)
    target[NAMES.index(destination)] = tuple(order)
    return exact_plan(initial, target)


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
