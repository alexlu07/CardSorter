"""Polishing: shorten a valid move list without ever making it longer.

  - cancel: delete adjacent inverse pairs;
  - remove_excursions: delete a card's move X->Y and its later return Y->X when, in between,
    stack X never drops below that level and is back at the same height;
  - Polisher.window_repair: replace any window that moves at most K cards, and starts or ends
    with exactly those cards on top of one stack, by its exact optimum from the tables
    (or by A* search for 10-11 cards in deep_polish) when that is shorter.

Every pass runs forwards and on the time reversal (the inverse deck), because the two find
different savings. `head` moves at the start (already executed, e.g. scanning) never change.
"""

from . import strategy_a as A
from .model import INVERSE, MIRROR, STACKS, inverse, piles, snapshots, time_reverse
from .tables import K, encode, top_segments


class Polisher:
    """Window repair and the polishing loops. `tables`: {'C': ExactTables, 'L': ExactTables}."""

    def __init__(self, tables):
        self.tables = tables

    def window_repair(self, deck, moves, home, kmin=1, kmax=K, solver=None, head=0, tail=0):
        """Replace windows that move kmin..kmax cards by exact optima. Returns (moves, changed).

        The first `head` and last `tail` moves are frozen (already executed) and never change.
        """
        solver = solver or self._exact
        moves = list(moves)
        changed = False
        t1 = head
        while True:
            confs, cards = snapshots(deck, moves, home)
            m = len(moves)
            hit = None
            while t1 < m - tail and hit is None:
                S = set()
                for t2 in range(t1 + 1, m - tail + 1):
                    S.add(cards[t2 - 1])
                    k = len(S)
                    if k > kmax:
                        break
                    length = t2 - t1
                    if length <= 2 or k < kmin:
                        continue
                    for end_side in (True, False):
                        anchor = confs[t2] if end_side else confs[t1]
                        other = confs[t1] if end_side else confs[t2]
                        for X in ('C', 'L', 'R'):
                            g = anchor[X]
                            if len(g) < k or set(g[-k:]) != S:
                                continue
                            segs = top_segments(other, S)
                            if sum(len(v) for v in segs.values()) != k:
                                continue
                            new = solver(segs, list(reversed(g[-k:])), X, length)
                            if new is not None:
                                if not end_side:
                                    new = [INVERSE[x] for x in reversed(new)]
                                hit = (t2, new)
                                break
                        if hit:
                            break
                    if hit:
                        break
                if hit is None:
                    t1 += 1
            if hit is None:
                return moves, changed
            t2, new = hit
            moves = moves[:t1] + new + moves[t2:]
            changed = True
            t1 = max(head, t1 - 1)

    def _exact(self, segs, order, X, length):
        """Shortest moves from top segments `segs` to `order` (top first) on stack X, if < length."""
        mirror = X == 'R'
        if mirror:
            segs = {MIRROR[s]: v for s, v in segs.items()}
            X = 'L'
        T = self.tables[X]
        rank = {v: i for i, v in enumerate(order)}
        cur = {s: [rank[v] for v in segs[s]] for s in STACKS}
        if T.dist_code(len(order), encode(cur['L'], cur['C'], cur['R'])) >= length:
            return None
        new = T.walk(segs, rank)
        return [(MIRROR[s], MIRROR[d]) for s, d in new] if mirror else new

    def _exact_search(self, segs, order, X, length):
        """A* (card_sorter) for blocks too large for the tables. Same contract as _exact."""
        rank = {v: i for i, v in enumerate(order, 1)}
        packed = (bytes(rank[v] for v in reversed(segs['L'])) + b'\0'
                  + bytes(rank[v] for v in segs['C']) + b'\0'
                  + bytes(rank[v] for v in reversed(segs['R'])))
        codes = A.shortest_to_pile(packed, bytes(range(1, len(order) + 1)), A.NAMES.index(X))
        if len(codes) >= length:
            return None
        return [(A.NAMES[A.EDGES[c][0]], A.NAMES[A.EDGES[c][1]]) for c in codes]

    def deep_polish(self, deck, moves, home, kmax=11, head=0):
        """polish, then also repair windows of K+1..kmax cards with A* search, forwards and reversed."""
        inv = inverse(deck)
        while True:
            before = len(moves)
            moves, _ = self.window_repair(deck, moves, home, K + 1, kmax, self._exact_search, head=head)
            back, _ = self.window_repair(inv, time_reverse(moves), home, K + 1, kmax, self._exact_search,
                                         tail=head)
            moves = self.polish_both_ways(deck, time_reverse(back), home, head=head)
            if len(moves) >= before:
                return moves

    def polish(self, deck, moves, home, head=0, tail=0):
        moves = cancel(moves, head, tail)
        while True:
            before = len(moves)
            moves = remove_excursions(deck, moves, home, head, tail)
            moves, _ = self.window_repair(deck, moves, home, head=head, tail=tail)
            if len(moves) == before:
                return moves

    def polish_both_ways(self, deck, moves, home, head=0):
        """Polish forwards and as the time reversal (inverse deck). The first `head` moves stay fixed."""
        best = self.polish(deck, moves, home, head=head)
        inv = inverse(deck)
        while True:
            back = time_reverse(self.polish(inv, time_reverse(best), home, tail=head))
            fwd = self.polish(deck, back, home, head=head)
            if len(fwd) >= len(best):
                return best
            best = fwd


def cancel(moves, head=0, tail=0):
    """Delete adjacent inverse pairs, except inside the frozen first `head` / last `tail` moves."""
    moves = list(moves)
    end = len(moves) - tail
    out = []
    for mv in moves[head:end]:
        if out and out[-1] == INVERSE[mv]:
            out.pop()
        else:
            out.append(mv)
    return moves[:head] + out + moves[end:]


def remove_excursions(deck, moves, home, head=0, tail=0):
    """Remove pointless excursions, leaving the frozen first `head` / last `tail` moves alone.

    Delete c: X->Y (time i) ... c: Y->X (time j) when, in between, stack X never drops below
    the level it had without c and is back at exactly that level at time j.
    """
    moves = list(moves)
    idx = {'L': 0, 'C': 1, 'R': 2}
    while True:
        st = piles(deck, home)
        cards, heights = [], []
        for s, d in moves:
            heights.append((len(st['L']), len(st['C']), len(st['R'])))
            st[d].append(st[s].pop())
            cards.append(st[d][-1])
        heights.append((len(st['L']), len(st['C']), len(st['R'])))
        m = len(moves) - tail
        done = False
        for i in range(head, m):
            X, Y = moves[i]
            c = cards[i]
            hx = heights[i][idx[X]] - 1
            j = i + 1
            ok = True
            while j < m and cards[j] != c:
                if heights[j + 1][idx[X]] < hx:
                    ok = False
                    break
                j += 1
            if ok and j < m and moves[j] == (Y, X) and heights[j][idx[X]] == hx:
                del moves[j]
                del moves[i]
                done = True
                break
        if not done:
            return moves
