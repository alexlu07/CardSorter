"""Strategy B: hub distribution (splits blocks by value, MSD-radix / quicksort style).

A block is the cards with values in [lo, hi] lying on top of a stack S; it must end sorted on
HOME, directly on the cards above hi. HubSorter.plan() runs a dynamic programme over value
interval x stack x order parity that picks the cheapest plan in this family for one deck, using
exact leaf costs from the tables; execute() plays it. worst_case_table() gives the family's
certified worst case (334 from C, 366 from a side with 9-card leaves).

Transitions: leaf (k <= K, exact table walk); trim (the block's deepest card is already in
place); pass (the block is two increasing chains: one excursion per card); split at t (values
> t to Pb, the rest to Pt, then solve Pb -> HOME and Pt -> HOME); transfer (move the whole
block to another stack, reversing it).
"""

import math

import numpy as np

from .model import STACKS, dist, piles as start_piles, route

def _split_options(S, home):
    others = [x for x in STACKS if x != S]
    if S != home:  # the upper part must land on HOME (it goes to the bottom of the final run)
        return [(home, [x for x in others if x != home][0])]
    return [(others[0], others[1]), (others[1], others[0])]


def worst_case_table(n, W, home='C'):
    """W[s][k] = exact worst case for a k-card block on stack s (k <= K).  Returns the worst-case
    table V[s][k] of the plan family for k = 0..n and the choice made at every (s, k)."""
    K = len(W['C']) - 1
    V = {s: [0] * (n + 1) for s in STACKS}
    how = {}
    for k in range(1, n + 1):
        if k <= K:
            for s in STACKS:
                V[s][k] = W[s][k]
                how[(s, k)] = ('exact',)
            continue
        cur = {}
        for S in STACKS:
            best = (math.inf, None)
            for a in range(1, k):  # a = size of the upper part, placed first
                for Pb, Pt in _split_options(S, home):
                    v = a * dist(S, Pb) + (k - a) * dist(S, Pt) + V[Pb][a] + V[Pt][k - a]
                    if v < best[0]:
                        best = (v, ('split', a, Pb, Pt))
            cur[S] = best
        changed = True
        while changed:
            changed = False
            for S in STACKS:
                for X in STACKS:
                    if X != S and k * dist(S, X) + cur[X][0] < cur[S][0]:
                        cur[S] = (k * dist(S, X) + cur[X][0], ('transfer', X))
                        changed = True
        for S in STACKS:
            V[S][k], how[(S, k)] = cur[S]
    return V, how

# ----------------------------------------------------------------------------------------------
# Per-deck optimal plan (interval DP) and execution
# ----------------------------------------------------------------------------------------------

def two_chain_assignment(arr):
    """If `arr` (values, top first) is a union of two increasing sequences, return the pile label
    (0 or 1) for each card, else None.  Greedy patience rule: put the card on the pile with the
    largest top that is still smaller than the card (optimal for two piles)."""
    tops = [0, 0]
    out = []
    for x in arr:
        best = None
        for i in (0, 1):
            if tops[i] < x and (best is None or tops[i] > tops[best]):
                best = i
        if best is None:
            return None
        tops[best] = x
        out.append(best)
    return out


class HubSorter:
    def __init__(self, tables):
        """`tables`: ExactTables whose goal is the home stack."""
        self.home = tables.goal
        self.K = tables.K
        self.T = tables

    def _pass_cost(self, piles):
        k = len(piles)
        if self.home == 'C':
            return 2 * k
        big = max(piles.count(0), piles.count(1))  # the larger chain goes through C (2 moves/card)
        return 2 * big + 4 * (k - big)            # the other through the far stack (4 moves/card)

    # -- planning ------------------------------------------------------------------------------
    def plan(self, deck):
        """F[s, p, lo, hi]: minimal cost (within the plan family) for block [lo,hi] lying on stack
        STACKS[s], in the deck's order restricted to [lo,hi], reversed if p = 1.  Returns (F, choice)."""
        n = len(deck)
        K, home = self.K, self.home
        sid = {s: i for i, s in enumerate(STACKS)}
        F = np.full((3, 2, n + 2, n + 2), np.inf)
        choice = {}
        opts = {S: _split_options(S, home) for S in STACKS}
        # HOME = C is symmetric under L <-> R: compute L, mirror it to R, and keep one split option.
        symmetric = home == 'C'
        sources = ('L', 'C') if symmetric else STACKS
        if symmetric:
            opts['C'] = [('L', 'R')]
        mir = {'L': 'R', 'R': 'L', 'C': 'C'}

        def mirror(c):
            if c[0] == 'split':
                return ('split', c[1], mir[c[2]], mir[c[3]])
            if c[0] == 'transfer':
                return ('transfer', mir[c[1]])
            return c

        def arr(lo, hi, p):
            a = [v for v in deck if lo <= v <= hi]
            return a[::-1] if p else a
        for length in range(1, n + 1):
            for lo in range(1, n - length + 2):
                hi = lo + length - 1
                ts = np.arange(lo, hi)
                for p in (0, 1):
                    a = arr(lo, hi, p)
                    for S in sources:
                        s = sid[S]
                        if length <= K:
                            F[s, p, lo, hi] = self.T.leaf_cost(a, S)
                            choice[(lo, hi, S, p)] = ('leaf',)
                            continue
                        best, bch = math.inf, None
                        if S == home:
                            if a[-1] == hi:
                                best, bch = F[s, p, lo, hi - 1], ('trim',)
                            piles = two_chain_assignment(a)
                            if piles is not None and self._pass_cost(piles) < best:
                                best, bch = self._pass_cost(piles), ('pass',)
                        for Pb, Pt in opts[S]:
                            v = ((hi - ts) * dist(S, Pb) + (ts - lo + 1) * dist(S, Pt)
                                 + F[sid[Pb], 1 - p, ts + 1, hi] + F[sid[Pt], 1 - p, lo, ts])
                            j = int(np.argmin(v))
                            if v[j] < best:
                                best, bch = float(v[j]), ('split', int(ts[j]), Pb, Pt)
                        F[s, p, lo, hi] = best
                        choice[(lo, hi, S, p)] = bch
                    if symmetric:
                        F[2, p, lo, hi] = F[0, p, lo, hi]
                        choice[(lo, hi, 'R', p)] = mirror(choice[(lo, hi, 'L', p)])
                if length > K:  # transfers between stacks of the same block (reverse its order)
                    changed = True
                    while changed:
                        changed = False
                        for p in (0, 1):
                            for S in STACKS:
                                for X in STACKS:
                                    if X != S:
                                        v = length * dist(S, X) + F[sid[X], 1 - p, lo, hi]
                                        if v < F[sid[S], p, lo, hi]:
                                            F[sid[S], p, lo, hi] = v
                                            choice[(lo, hi, S, p)] = ('transfer', X)
                                            changed = True
        return F, choice

    # -- execution -----------------------------------------------------------------------------
    def execute(self, deck, choice):
        n = len(deck)
        home = self.home
        st = start_piles(deck, home)
        moves = []

        def go(src, dst):  # carry one card, through C if needed
            for s, d in route(src, dst):
                st[d].append(st[s].pop())
                moves.append((s, d))

        def run(lo, hi, S, p):
            if lo > hi:
                return
            ch = choice[(lo, hi, S, p)]
            kind = ch[0]
            k = hi - lo + 1
            if kind == 'leaf':
                moves.extend(self.T.solve_block(st, set(range(lo, hi + 1))))
            elif kind == 'trim':
                run(lo, hi - 1, S, p)
            elif kind == 'pass':  # one excursion per card: two increasing chains, then a merge
                block = list(reversed(st[home][-k:]))  # top first
                piles = two_chain_assignment(block)
                if home == 'C':
                    dest = {0: 'L', 1: 'R'}
                else:
                    big = 0 if piles.count(0) >= piles.count(1) else 1
                    far = 'R' if home == 'L' else 'L'
                    dest = {big: 'C', 1 - big: far}
                left = {dest[0]: 0, dest[1]: 0}
                for pile in piles:
                    go(home, dest[pile])
                    left[dest[pile]] += 1
                for _ in range(k):  # merge: the larger visible card goes home first
                    s = max((q for q in left if left[q] > 0), key=lambda q: st[q][-1])
                    go(s, home)
                    left[s] -= 1
            elif kind == 'transfer':
                X = ch[1]
                for _ in range(k):
                    go(S, X)
                run(lo, hi, X, 1 - p)
            else:  # split: upper part -> Pb, lower part -> Pt
                _, t, Pb, Pt = ch
                for _ in range(k):
                    go(S, Pb if st[S][-1] > t else Pt)
                run(t + 1, hi, Pb, 1 - p)
                run(lo, t, Pt, 1 - p)
        run(1, n, home, 0)
        return moves
