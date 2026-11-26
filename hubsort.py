#!/usr/bin/env python3
"""
hubsort.py - minimum-movement sorting for the three-compartment (LEFT - CENTER - RIGHT) card machine.

Model
-----
* Three LIFO stacks L, C, R.  Only top cards move, one card per movement.
* Cost: L<->C = 1, C<->R = 1, L<->R = 2 (identical to L->C followed by C->R).
* Start: all n cards in the HOME compartment (top..bottom = deck[0..n-1]); cards are labelled
  1..n by final position.  HOME is C (the original problem) or a side compartment L or R.
* Goal: HOME holds 1,2,...,n from top to bottom; the other two compartments are empty.

Because an L<->R transfer is exactly two adjacent transfers, every movement sequence can be
written with adjacent transfers only and the total cost is the number of adjacent transfers.

Algorithm (summary; see the accompanying report for proofs)
----------------------------------------------------------
1. Exact tables.  For every k <= K (default K = 9) a breadth-first search over all
   k! * (k+1)(k+2)/2 configurations of k cards gives the exact minimum number of moves from any
   configuration to "k cards sorted on HOME".  (Built with numpy in a few seconds.)
2. Plan family ("hub distribution").  A block = the cards with values in an interval [lo, hi],
   lying on top of one stack S; it must end sorted on HOME, directly on the cards > hi.
   Transitions:
      leaf        |block| <= K : play an exact optimal solution from the table;
      trim        S = HOME and the deepest card of the block is hi : it is already in place;
      pass        S = HOME and the block is a union of two increasing sequences: one excursion per
                  card (HOME = C: 2 moves per card; HOME = side: 2 or 4 moves per card);
      split at t  pop the block from S; values > t go to stack Pb, values <= t to stack Pt
                  (1 move each, or 2 when L<->R), then sort the upper part (Pb -> HOME), then the
                  lower part (Pt -> HOME).  If S != HOME then Pb = HOME (the upper part lands in place);
      transfer    move the whole block to another stack (reverses its order).
3. Per-deck optimisation.  A dynamic programme over value intervals (O(n^3)) picks the cheapest
   plan for the given deck, using exact leaf costs.  The same is done for the inverse deck and the
   time-reversed solution is used if it is cheaper (time reversal maps distribution plans to merge
   plans).  Polishing (never adds moves): remove "pointless excursions" (a card that leaves a
   stack and comes back without anything below it being touched), and re-solve exactly every
   window that moves <= K cards and starts or ends with exactly those cards on top of HOME.
4. Guarantee.  With W_S(k) = worst case for a k-card block on S (exact for k <= K):
      W_S(k) = min over a and the allowed (Pb, Pt) of [ a*d(S,Pb) + (k-a)*d(S,Pt) + W_Pb(a) + W_Pt(k-a) ]
               (and transfers W_S(k) <= k*d(S,X) + W_X(k)).
   For 52 cards and K = 9:  HOME = C  ->  334 movements;  HOME = L or R  ->  366 movements.

Lower bounds (proved in the report): the reversed deck 52,51,...,1 needs exactly 4(n-1) = 204
moves when HOME = C and exactly 4n-2 = 206 when HOME is a side compartment.

Usage
-----
  python3 hubsort.py                      # demo on one random 52-card deck (HOME = C)
  python3 hubsort.py --home L             # same, cards start and finish in LEFT
  python3 hubsort.py --deck 52,51,...,1   # solve a given deck (comma separated, top first)
  python3 hubsort.py --random 200         # statistics on random decks
  python3 hubsort.py --bound              # print the worst-case recurrence table
  python3 hubsort.py --show               # also print the movement list
"""
import argparse
import itertools
import math
import os
import random
import sys
import time
from bisect import bisect_left

import numpy as np

STACKS = ('L', 'C', 'R')
ADJ_COST = {('L', 'C'): 1, ('C', 'L'): 1, ('C', 'R'): 1, ('R', 'C'): 1, ('L', 'R'): 2, ('R', 'L'): 2}
_INV = {('C', 'L'): ('L', 'C'), ('L', 'C'): ('C', 'L'), ('C', 'R'): ('R', 'C'), ('R', 'C'): ('C', 'R')}


def dcost(x, y):
    """Cost of moving one card from stack x to stack y."""
    if x == y:
        return 0
    return 1 if 'C' in (x, y) else 2


def route(x, y):
    """Adjacent moves that carry the top card of x to the top of y."""
    if 'C' in (x, y):
        return [(x, y)]
    return [(x, 'C'), ('C', y)]


def _start(deck, home):
    st = {'L': [], 'C': [], 'R': []}  # top of a stack = end of its list
    st[home] = list(reversed(deck))
    return st

# ----------------------------------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------------------------------

def verify(deck, moves, home='C'):
    """Replay `moves` on `deck` (HOME top..bottom) and check every movement and the final state.

    moves: iterable of (src, dst) pairs or strings like 'C->L'.  L->R and R->L are accepted and
    counted as 2 adjacent transfers.  Returns a dict with keys ok, cost, movements, message.
    """
    n = len(deck)
    if sorted(deck) != list(range(1, n + 1)):
        return {'ok': False, 'cost': None, 'movements': 0, 'message': 'deck is not a permutation of 1..n'}
    if home not in STACKS:
        return {'ok': False, 'cost': None, 'movements': 0, 'message': 'home must be L, C or R'}
    st = _start(deck, home)
    cost = 0
    count = 0
    for idx, mv in enumerate(moves):
        if isinstance(mv, str):
            src, dst = mv.replace(' ', '').split('->')
        else:
            src, dst = mv
        if (src, dst) not in ADJ_COST:
            return {'ok': False, 'cost': cost, 'movements': count, 'message': f'move {idx}: illegal transfer {src}->{dst}'}
        if not st[src]:
            return {'ok': False, 'cost': cost, 'movements': count, 'message': f'move {idx}: {src} is empty'}
        st[dst].append(st[src].pop())
        cost += ADJ_COST[(src, dst)]
        count += 1
    others_empty = all(not st[s] for s in STACKS if s != home)
    final_ok = others_empty and list(reversed(st[home])) == list(range(1, n + 1))
    msg = 'sorted' if final_ok else f"final state wrong: L={st['L'][::-1]} C={st['C'][::-1]} R={st['R'][::-1]}"
    return {'ok': final_ok, 'cost': cost, 'movements': count, 'message': msg}


def compress(moves):
    """Merge each L->C immediately followed by C->R into one L->R (cost 2), and R->C,C->L into R->L."""
    out = []
    for m in moves:
        if out and out[-1] == ('L', 'C') and m == ('C', 'R'):
            out[-1] = ('L', 'R')
        elif out and out[-1] == ('R', 'C') and m == ('C', 'L'):
            out[-1] = ('R', 'L')
        else:
            out.append(m)
    return out


def expand(moves):
    """Inverse of compress: replace L->R / R->L by two adjacent transfers."""
    out = []
    for m in moves:
        out += route(*m) if m in (('L', 'R'), ('R', 'L')) else [m]
    return out


def _simulate(deck, moves, home):
    st = _start(deck, home)
    confs = [{k: list(v) for k, v in st.items()}]
    cards = []
    for s, d in moves:
        c = st[s].pop()
        st[d].append(c)
        cards.append(c)
        confs.append({k: list(v) for k, v in st.items()})
    return confs, cards


def remove_pointless_excursions(deck, moves, home='C'):
    """Delete pairs of moves  c: X->Y (time i) ... c: Y->X (time j)  when, in between, stack X never
    drops below the level it had without c and is back at exactly that level at time j.  Then c can
    simply stay on X: every intermediate move sees the same cards, so the result is unchanged and
    the sequence is 2 moves shorter.  (Includes immediate cancellations X->Y, Y->X.)"""
    moves = list(moves)
    idx = {'L': 0, 'C': 1, 'R': 2}
    while True:
        st = _start(deck, home)
        cards, heights = [], []
        for s, d in moves:
            heights.append((len(st['L']), len(st['C']), len(st['R'])))
            c = st[s].pop()
            st[d].append(c)
            cards.append(c)
        heights.append((len(st['L']), len(st['C']), len(st['R'])))
        m = len(moves)
        done = False
        for i in range(m):
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

# ----------------------------------------------------------------------------------------------
# Lower bounds
# ----------------------------------------------------------------------------------------------

def _rsk_rows(seq):
    """Lengths of the first two rows of the RSK shape: lambda1 = longest increasing subsequence,
    lambda1 + lambda2 = largest union of two increasing subsequences (Greene's theorem)."""
    r1, r2 = [], []
    for x in seq:
        i = bisect_left(r1, x)
        if i == len(r1):
            r1.append(x)
            continue
        y, r1[i] = r1[i], x
        j = bisect_left(r2, y)
        if j == len(r2):
            r2.append(y)
        else:
            r2[j] = y
    return len(r1), len(r2)


def structural_lower_bound(deck, home='C'):
    """Proven per-deck lower bound.

    z = number of bottom cards already in final position (n, n-1, ... at the very bottom); they
    never need to move.  Every other card moves an even number >= 2 of times.
      HOME = C   : cards moving exactly twice that use the same outer stack keep their order, so
                   they form <= 2 increasing subsequences  ->  4(n-z) - 2(lambda1 + lambda2).
      HOME = side: a card moving exactly twice goes HOME->C->HOME; all such cards are nested in C
                   and keep their order, so they form ONE increasing subsequence -> 4(n-z) - 2*lambda1.
    """
    n = len(deck)
    z = 0
    while z < n and deck[n - 1 - z] == n - z:
        z += 1
    top = deck[:n - z]
    if not top:
        return 0
    l1, l2 = _rsk_rows(top)
    return 4 * len(top) - 2 * (l1 + l2 if home == 'C' else l1)


def worst_case_lower_bound(n, home='C'):
    """Proven: the reversed deck needs exactly 4(n-1) moves (HOME = C) or 4n-2 (side HOME)."""
    if n < 2:
        return 0
    return 4 * (n - 1) if home == 'C' else 4 * n - 2


def counting_lower_bound(n):
    """Proven (weaker for n=52) bound: an optimal sequence never undoes its previous move and its
    first move can be fixed (mirror symmetry for HOME = C; forced for a side HOME), so there are
    < 9/8 * 3^(m-1) sequences of length <= m; this must be >= n!."""
    target = math.lgamma(n + 1) / math.log(3)  # log_3 n!
    m = 2
    while (m - 1) + math.log(9 / 8, 3) < target:
        m += 2
    return m

# ----------------------------------------------------------------------------------------------
# Exact tables (vectorised BFS)
# ----------------------------------------------------------------------------------------------
_SH_A, _SH_B = 40, 44
_NIB = np.int64(0xF)


def _mask(lengths):
    return (np.left_shift(np.int64(1), (4 * lengths).astype(np.int64)) - 1).astype(np.int64)


def _rot_right(code, i, j):  # new[i] = old[j], new[i+1..j] = old[i..j-1]
    L = j - i + 1
    m = _mask(L)
    seg = np.right_shift(code, 4 * i) & m
    last = np.right_shift(seg, 4 * (L - 1)) & _NIB
    new = np.left_shift(seg & _mask(L - 1), 4) | last
    return (code & ~np.left_shift(m, 4 * i)) | np.left_shift(new, 4 * i)


def _rot_left(code, i, j):  # new[j] = old[i], new[i..j-1] = old[i+1..j]
    L = j - i + 1
    m = _mask(L)
    seg = np.right_shift(code, 4 * i) & m
    new = np.right_shift(seg, 4) | np.left_shift(seg & _NIB, 4 * (L - 1))
    return (code & ~np.left_shift(m, 4 * i)) | np.left_shift(new, 4 * i)


def _neighbors(codes, k):
    a = np.right_shift(codes, _SH_A) & _NIB
    b = np.right_shift(codes, _SH_B) & _NIB
    c = k - a - b
    base = codes & ((np.int64(1) << 40) - 1)
    out = []
    s = b > 0  # C->L
    if s.any():
        out.append(_rot_right(base[s], a[s], a[s] + b[s] - 1) | np.left_shift(a[s] + 1, _SH_A) | np.left_shift(b[s] - 1, _SH_B))
    s = a > 0  # L->C
    if s.any():
        out.append(_rot_left(base[s], a[s] - 1, a[s] + b[s] - 1) | np.left_shift(a[s] - 1, _SH_A) | np.left_shift(b[s] + 1, _SH_B))
    s = b > 0  # C->R
    if s.any():
        km1 = np.full(int(s.sum()), k - 1, dtype=np.int64)
        out.append(_rot_left(base[s], a[s] + b[s] - 1, km1) | np.left_shift(a[s], _SH_A) | np.left_shift(b[s] - 1, _SH_B))
    s = c > 0  # R->C
    if s.any():
        km1 = np.full(int(s.sum()), k - 1, dtype=np.int64)
        out.append(_rot_right(base[s], a[s] + b[s], km1) | np.left_shift(a[s], _SH_A) | np.left_shift(b[s] + 1, _SH_B))
    return np.concatenate(out)


def encode(Ltop, Ctop, Rtop):
    """Configuration of k cards with values 0..k-1, stacks given top-first."""
    code = 0
    i = 0
    for stack in (Ltop, Ctop, Rtop):
        for v in reversed(stack):
            code |= v << (4 * i)
            i += 1
    return code | (len(Ltop) << _SH_A) | (len(Ctop) << _SH_B)


def _encode_on(stack, seq):
    return encode(seq if stack == 'L' else [], seq if stack == 'C' else [], seq if stack == 'R' else [])


def build_table(k, goal='C'):
    """BFS from 'k cards sorted on `goal`' over all configurations (the move graph is undirected, so
    layer d+1 = N(layer d) minus layers d and d-1).  Returns (sorted codes, distances)."""
    prev = np.array([], dtype=np.int64)
    cur = np.array([_encode_on(goal, list(range(k)))], dtype=np.int64)
    layers = [cur]
    while True:
        nb = np.unique(_neighbors(cur, k))
        nb = nb[~np.isin(nb, cur, assume_unique=True)]
        nb = nb[~np.isin(nb, prev, assume_unique=True)]
        if nb.size == 0:
            break
        prev, cur = cur, nb
        layers.append(cur)
    codes = np.concatenate(layers)
    dist = np.concatenate([np.full(l.size, d, dtype=np.uint8) for d, l in enumerate(layers)])
    order = np.argsort(codes)
    return codes[order], dist[order]


class ExactTables:
    """Exact distances from every configuration of k <= K cards to 'sorted on `goal`'."""

    def __init__(self, K=9, goal='C', verbose=False, cache_dir=None):
        self.K = K
        self.goal = goal
        self.tab = {}
        t0 = time.time()
        for k in range(1, K + 1):
            path = None if cache_dir is None else os.path.join(cache_dir, f'table_{goal}_{k}.npz')
            if path and os.path.exists(path):
                with np.load(path) as f:
                    self.tab[k] = (f['codes'], f['dist'])
                continue
            self.tab[k] = build_table(k, goal)
            if path:
                os.makedirs(cache_dir, exist_ok=True)
                np.savez(path + '.tmp.npz', codes=self.tab[k][0], dist=self.tab[k][1])
                os.replace(path + '.tmp.npz', path)
        if verbose:
            print('[tables] exact BFS tables (goal %s, k<=%d) built in %.1fs' % (goal, K, time.time() - t0), file=sys.stderr)
        self._worst = None

    def dist_code(self, k, code):
        codes, dist = self.tab[k]
        i = int(np.searchsorted(codes, code))
        assert i < codes.size and codes[i] == code
        return int(dist[i])

    def leaf_cost(self, arr, src):
        """Exact optimum for block `arr` (values, top-first) entirely on `src`."""
        k = len(arr)
        if k == 0:
            return 0
        rank = {v: i for i, v in enumerate(sorted(arr))}
        return self.dist_code(k, _encode_on(src, [rank[v] for v in arr]))

    def worst_cases(self):
        """Exact worst case over all k! orders of a block that lies entirely on L, C or R."""
        if self._worst is None:
            W = {s: [0] for s in STACKS}
            for k in range(1, self.K + 1):
                codes, dist = self.tab[k]
                perms = np.array(list(itertools.permutations(range(k))), dtype=np.int64)
                seq = perms[:, ::-1]  # bottom..top
                base = np.zeros(len(perms), dtype=np.int64)
                for i in range(k):
                    base |= seq[:, i] << (4 * i)
                for s, (a, b) in (('L', (k, 0)), ('C', (0, k)), ('R', (0, 0))):
                    q = base | (a << _SH_A) | (b << _SH_B)
                    W[s].append(int(dist[np.searchsorted(codes, q)].max()))
            self._worst = W
        return self._worst

    def walk(self, segs, rank):
        """Optimal adjacent moves from the configuration whose block cards occupy the top segments
        `segs` (top-first lists of card values) to 'block on top of the goal stack in the order
        given by rank (0 = top)'."""
        k = len(rank)
        cur = {s: [rank[v] for v in segs[s]] for s in STACKS}
        d = self.dist_code(k, encode(cur['L'], cur['C'], cur['R']))
        out = []
        while d > 0:
            for src, dst in (('C', 'L'), ('C', 'R'), ('L', 'C'), ('R', 'C')):
                if not cur[src]:
                    continue
                nxt = {s: list(v) for s, v in cur.items()}
                nxt[dst].insert(0, nxt[src].pop(0))
                d2 = self.dist_code(k, encode(nxt['L'], nxt['C'], nxt['R']))
                if d2 == d - 1:
                    out.append((src, dst))
                    cur, d = nxt, d2
                    break
            else:
                raise RuntimeError('table walk failed')
        return out

    def solve_block(self, st, block):
        """Play an optimal sequence that brings the cards of `block` (a set of values occupying the
        top segments of the stacks in simulator state `st`) sorted onto the top of the goal stack."""
        segs = _top_segments(st, block)
        assert sum(len(x) for x in segs.values()) == len(block), 'block cards must occupy top segments'
        rank = {v: i for i, v in enumerate(sorted(block))}
        moves = self.walk(segs, rank)
        for s, d in moves:
            st[d].append(st[s].pop())
        return moves


def _top_segments(conf, S):
    out = {}
    for s in STACKS:
        seg = []
        for v in reversed(conf[s]):
            if v in S:
                seg.append(v)
            else:
                break
        out[s] = seg
    return out

# ----------------------------------------------------------------------------------------------
# Worst-case recurrence (the guaranteed bound)
# ----------------------------------------------------------------------------------------------

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
                    v = a * dcost(S, Pb) + (k - a) * dcost(S, Pt) + V[Pb][a] + V[Pt][k - a]
                    if v < best[0]:
                        best = (v, ('split', a, Pb, Pt))
            cur[S] = best
        changed = True
        while changed:
            changed = False
            for S in STACKS:
                for X in STACKS:
                    if X != S and k * dcost(S, X) + cur[X][0] < cur[S][0]:
                        cur[S] = (k * dcost(S, X) + cur[X][0], ('transfer', X))
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
    def __init__(self, K=9, home='C', verbose=False, tables=None):
        assert home in STACKS
        self.home = home
        self.K = K
        self.T = tables if tables is not None else ExactTables(K, goal=home, verbose=verbose)
        assert self.T.K == K and self.T.goal == home

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
                            v = ((hi - ts) * dcost(S, Pb) + (ts - lo + 1) * dcost(S, Pt)
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
                                        v = length * dcost(S, X) + F[sid[X], 1 - p, lo, hi]
                                        if v < F[sid[S], p, lo, hi]:
                                            F[sid[S], p, lo, hi] = v
                                            choice[(lo, hi, S, p)] = ('transfer', X)
                                            changed = True
        return F, choice

    # -- execution -----------------------------------------------------------------------------
    def execute(self, deck, choice):
        n = len(deck)
        home = self.home
        st = _start(deck, home)
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

    def sort_deck(self, deck, use_inverse=True, polish=True):
        """Return (adjacent-move list, cost, info).  Cost never exceeds the worst-case bound:
        the planned cost is <= the fixed worst-case plan on this deck, and polishing only removes
        moves."""
        n = len(deck)
        assert sorted(deck) == list(range(1, n + 1)), 'deck must be a permutation of 1..n'
        home = self.home
        h = STACKS.index(home)
        F, ch = self.plan(deck)
        best_cost = int(F[h, 0, 1, n])
        moves = self.execute(deck, ch)
        assert len(moves) == best_cost
        info = {'direction': 'forward', 'planned': best_cost}
        if use_inverse:
            inv = [0] * n
            for i, v in enumerate(deck):
                inv[v - 1] = i + 1
            F2, ch2 = self.plan(inv)
            c2 = int(F2[h, 0, 1, n])
            if c2 < best_cost:
                m2 = self.execute(inv, ch2)
                moves = [(d, s) for (s, d) in reversed(m2)]  # time reversal
                best_cost = c2
                info = {'direction': 'time-reversed plan of inverse deck', 'planned': c2}
        if polish:
            m1 = remove_pointless_excursions(deck, moves, home)
            m1 = table_peephole(deck, m1, self.T, home)
            m1 = remove_pointless_excursions(deck, m1, home)
            chk = verify(deck, m1, home)
            if chk['ok'] and chk['cost'] <= best_cost:  # safety net: keep the plan if anything is off
                moves, best_cost = m1, chk['cost']
        info['final'] = best_cost
        return moves, best_cost, info

    def guaranteed_bound(self, n):
        V, how = worst_case_table(n, self.T.worst_cases(), self.home)
        return V[self.home][n]


def table_peephole(deck, moves, tables, home='C'):
    """Window re-optimisation.  For a window of the sequence that moves a set S of <= K cards and
    that starts or ends with exactly the cards of S on top of the table's goal stack, the exact
    table gives the true minimum for that window (by the projection argument the other cards are
    irrelevant).  Replace any window that is longer than that minimum.  Never increases the cost."""
    K, G = tables.K, tables.goal
    moves = list(moves)
    while True:
        confs, cards = _simulate(deck, moves, home)
        m = len(moves)
        replaced = False
        for t1 in range(m):
            S = set()
            for t2 in range(t1 + 1, m + 1):
                S.add(cards[t2 - 1])
                k = len(S)
                if k > K:
                    break
                length = t2 - t1
                if length <= 2:
                    continue
                for end_side in (True, False):
                    anchor = confs[t2] if end_side else confs[t1]
                    other = confs[t1] if end_side else confs[t2]
                    g = anchor[G]
                    if len(g) < k or set(g[-k:]) != S:
                        continue
                    rank = {v: i for i, v in enumerate(reversed(g[-k:]))}
                    segs = _top_segments(other, S)
                    cur = {s: [rank[v] for v in segs[s]] for s in STACKS}
                    if tables.dist_code(k, encode(cur['L'], cur['C'], cur['R'])) < length:
                        new = tables.walk(segs, rank)
                        if not end_side:
                            new = [_INV[x] for x in reversed(new)]
                        moves = moves[:t1] + new + moves[t2:]
                        replaced = True
                        break
                if replaced:
                    break
            if replaced:
                break
        if not replaced:
            return moves


def optimal_cost_small(deck, tables):
    """Exact optimum for decks with n <= K (table lookup); the deck starts on the table's goal stack."""
    return tables.leaf_cost(list(deck), tables.goal)

# ----------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------

def fmt(moves):
    return ' '.join(f'{s}->{d}' for s, d in moves)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--deck', help='comma-separated deck, top card first, values 1..n')
    ap.add_argument('--home', default='C', choices=STACKS, help='compartment where the deck starts and ends')
    ap.add_argument('--random', type=int, default=0, help='run N random decks and report statistics')
    ap.add_argument('--n', type=int, default=52)
    ap.add_argument('--K', type=int, default=9, help='exact leaf size (<= 9 recommended)')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--bound', action='store_true', help='print the worst-case recurrence')
    ap.add_argument('--show', action='store_true', help='print the movement list (L->R shown as one move)')
    args = ap.parse_args()

    hs = HubSorter(K=args.K, home=args.home, verbose=True)
    if args.bound:
        V, how = worst_case_table(args.n, hs.T.worst_cases(), args.home)
        print(f'worst-case table, deck starts and ends on {args.home}; columns = block on L, C, R')
        for k in range(1, args.n + 1):
            print(f"{k:2d}  L {V['L'][k]:4d}  C {V['C'][k]:4d}  R {V['R'][k]:4d}   home choice {how[(args.home, k)]}")
        print(f'Guaranteed worst case for n={args.n}: {V[args.home][args.n]} movements; '
              f'proven lower bound: {worst_case_lower_bound(args.n, args.home)}')
        return
    rng = random.Random(args.seed)
    decks = []
    if args.deck:
        decks = [[int(x) for x in args.deck.split(',')]]
    elif args.random:
        for _ in range(args.random):
            d = list(range(1, args.n + 1)); rng.shuffle(d); decks.append(d)
    else:
        d = list(range(1, args.n + 1)); rng.shuffle(d); decks = [d]
    costs = []
    t0 = time.time()
    for deck in decks:
        moves, cost, info = hs.sort_deck(deck)
        chk = verify(deck, moves, args.home)
        assert chk['ok'] and chk['cost'] == cost, chk
        chk2 = verify(deck, compress(moves), args.home)
        assert chk2['ok'] and chk2['cost'] == cost, chk2
        costs.append(cost)
        if len(decks) == 1:
            print(f'deck in {args.home} (top..bottom):', ','.join(map(str, deck)))
            print(f'movement cost: {cost}   (plan {info["planned"]}, {info["direction"]}; after polishing {cost})')
            print(f'structural lower bound for this deck: {structural_lower_bound(deck, args.home)}')
            print(f'guaranteed bound for n={len(deck)}: {hs.guaranteed_bound(len(deck))}')
            print('verification:', chk['message'], '| cost', chk['cost'])
            if args.show:
                print(fmt(compress(moves)))
    if len(decks) > 1:
        print(f'{len(decks)} decks (home {args.home}): mean {np.mean(costs):.2f}  max {max(costs)}  min {min(costs)}  '
              f'(all verified; {time.time()-t0:.1f}s)')
        print(f'guaranteed bound: {hs.guaranteed_bound(args.n)}   '
              f'proven lower bound on the worst case: {worst_case_lower_bound(args.n, args.home)}')


if __name__ == '__main__':
    main()
