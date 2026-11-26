"""Shared vocabulary: stacks, moves, decks, and an independent replay that checks every move.

Stacks are the letters L, C, R (left, center/middle, right). Hardware and the visualizer use
the names in NAMES. Decks list cards top first, labelled 1..n by final position: the goal is
1..n top to bottom on the starting stack, with the other two stacks empty.

Planners work with (source, destination) letter pairs. Public results are Move records, which
also carry the card that moves.
"""

from typing import NamedTuple

STACKS = ('L', 'C', 'R')
NAMES = {'L': 'left', 'C': 'center', 'R': 'right'}
MIRROR = {'L': 'R', 'C': 'C', 'R': 'L'}
INVERSE = {('C', 'L'): ('L', 'C'), ('L', 'C'): ('C', 'L'), ('C', 'R'): ('R', 'C'), ('R', 'C'): ('C', 'R')}
ADJACENT = frozenset(INVERSE)


class Move(NamedTuple):
    source: str
    destination: str
    card: int


def letter(stack):
    """'L', 'left', 'Left' ... -> 'L'. Raises ValueError for anything else."""
    if isinstance(stack, str):
        key = stack.strip().lower()
        for code, name in NAMES.items():
            if key in (code.lower(), name, 'middle' if code == 'C' else name):
                return code
    raise ValueError('A stack must be L, C, or R (left, center, or right).')


def dist(x, y):
    """Adjacent moves needed to carry one card from stack x to stack y."""
    return abs(STACKS.index(x) - STACKS.index(y))


def route(x, y):
    """Adjacent (source, destination) pairs that carry the top card of x to the top of y."""
    if x == y:
        return []
    if 'C' in (x, y):
        return [(x, y)]
    return [(x, 'C'), ('C', y)]


def check_deck(values):
    """Validate a deck of 1..52 distinct labels (top first) and return it as a tuple."""
    cards = tuple(values)
    if not 1 <= len(cards) <= 52 or any(type(x) is not int for x in cards):
        raise ValueError('Supply 1 through 52 integer card labels.')
    if sorted(cards) != list(range(1, len(cards) + 1)):
        raise ValueError('Expected each label from 1 to the deck size exactly once.')
    return cards


def inverse(deck):
    """The inverse permutation. Sorting it, played time-reversed, sorts `deck`."""
    inv = [0] * len(deck)
    for i, v in enumerate(deck):
        inv[v - 1] = i + 1
    return inv


def time_reverse(pairs):
    """Reverse a move list and invert each move."""
    return [(d, s) for s, d in reversed(pairs)]


def mirror(pairs):
    """Swap L and R in every move."""
    return [(MIRROR[s], MIRROR[d]) for s, d in pairs]


# -- fast replay for planners: piles are bottom-first lists, so the top is the end ----------

def piles(deck, home):
    """{stack: bottom-first list} with the whole deck on `home`."""
    st = {'L': [], 'C': [], 'R': []}
    st[home] = list(reversed(deck))
    return st


def snapshots(deck, pairs, home):
    """(configuration before each move and after the last, card moved by each move)."""
    st = piles(deck, home)
    confs = [{k: list(v) for k, v in st.items()}]
    cards = []
    for s, d in pairs:
        st[d].append(st[s].pop())
        cards.append(st[d][-1])
        confs.append({k: list(v) for k, v in st.items()})
    return confs, cards


def sorts(deck, pairs, home):
    """True when the adjacent `pairs` legally take `deck` from home to sorted on home."""
    st = piles(deck, home)
    for s, d in pairs:
        if (s, d) not in ADJACENT or not st[s]:
            return False
        st[d].append(st[s].pop())
    others = all(not st[x] for x in STACKS if x != home)
    return others and st[home] == list(range(len(deck), 0, -1))


def label(deck, pairs, start):
    """Move records for (source, destination) pairs played from `deck` on `start`."""
    st = piles(deck, start)
    out = []
    for s, d in pairs:
        st[d].append(st[s].pop())
        out.append(Move(s, d, st[d][-1]))
    return out


# -- independent checks on Move records -----------------------------------------------------

def check_stacks(stacks):
    """Normalise (L, C, R) top-first stacks to tuples; cards must be distinct and hashable."""
    result = tuple(tuple(s) for s in stacks)
    if len(result) != 3:
        raise ValueError('Expected left, center, right stacks')
    cards = [c for s in result for c in s]
    if len(set(cards)) != len(cards):
        raise ValueError('Card IDs must be distinct and hashable')
    return result


def apply_moves(stacks, moves, *, protected=(0, 0, 0)):
    """Replay Move records on (L, C, R) top-first stacks and return the result.

    Rejects non-adjacent moves, a card that is not on top, and removing any of the
    `protected` bottom cards of a stack.
    """
    stacks = [list(s) for s in check_stacks(stacks)]
    if len(protected) != 3 or any(type(n) is not int or not 0 <= n <= len(s)
                                  for n, s in zip(protected, stacks)):
        raise ValueError('Invalid protected bottom-card counts')
    for move in moves:
        source, destination = STACKS.index(move.source), STACKS.index(move.destination)
        if abs(source - destination) != 1:
            raise ValueError('Only adjacent transfers are legal')
        if len(stacks[source]) <= protected[source]:
            raise ValueError('Cannot remove a protected card')
        if stacks[source][0] != move.card:
            raise ValueError('Moved card is not on top')
        stacks[destination].insert(0, stacks[source].pop(0))
    return tuple(tuple(s) for s in stacks)


def verify(deck, moves, *, start='C'):
    """Independently replay (source, destination, card) triples and return the move count.

    Raise ValueError at the first illegal move or if the final state is wrong.
    """
    order = check_deck(deck)
    start = letter(start)
    stacks = {'L': [], 'C': [], 'R': []}
    stacks[start] = list(reversed(order))
    cost = 0
    for cost, command in enumerate(moves, 1):
        try:
            source, destination, card = command
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Move {cost}: expected (source, destination, card).') from exc
        if (source, destination) not in ADJACENT:
            raise ValueError(f'Move {cost}: compartments must be adjacent.')
        if type(card) is not int or not stacks[source] or stacks[source][-1] != card:
            raise ValueError(f'Move {cost}: {card!r} is not on top of {source}.')
        if len(stacks[destination]) >= 52:
            raise ValueError(f'Move {cost}: the destination is full.')
        stacks[destination].append(stacks[source].pop())
    if (stacks[start] != list(range(len(order), 0, -1))
            or any(stack for name, stack in stacks.items() if name != start)):
        raise ValueError(f'The final state does not have the whole deck sorted in {start}.')
    return cost
