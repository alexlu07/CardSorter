#!/usr/bin/env python3
"""Combined planner: Strategy A (certified block merge, card_sorter.py) plus
Strategy B (per-deck hub distribution, hubsort.py), with polishing on every candidate.

For each deck:
  1. Strategy A generates all of its variants. Each one is certified within
     322 moves (centre start) or 350 (side start).
  2. Strategy B's per-deck interval DP runs forwards and on the inverse deck.
     The inverse plan is played time-reversed.
  3. Every candidate is polished. Polishing only ever deletes or shortens moves:
       - pointless-excursion removal (generalises adjacent cancellation);
       - exact window repair. Any window that moves <= K cards and starts or ends
         with exactly those cards on top of one stack is replaced by an exact
         optimum when that is shorter. Unlike hubsort.py, the anchor may be any
         stack, not only the home stack.
     Each candidate is polished forwards and also as its time reversal (which
     sorts the inverse deck), because the two passes find different savings.
  4. The shortest result is replayed by card_sorter.verify. The planner asserts
     that it is within the certified bound.

The machine itself does not know the order in advance: its camera reads only the top of the
starting pile. Planner.plan_scanned plans the scan-first version (phase 1 routes each card by
value as the camera reads it; phase 2 uses the candidates and polishing above on the known
layout), with the same 322 / 350 bounds.

Decks are top first. Moves are card_sorter.Move(source, destination, card), adjacent only.

    python combined_sorter.py --seed 42 --start L
"""

import argparse
import os
import random
import time

import card_sorter as A
import hubsort as B

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.table_cache')
K = 9
MIRROR = {'L': 'R', 'C': 'C', 'R': 'L'}
INVERSE = {('C', 'L'): ('L', 'C'), ('L', 'C'): ('C', 'L'), ('C', 'R'): ('R', 'C'), ('R', 'C'): ('C', 'R')}
BOUND = {'C': 322, 'L': 350, 'R': 350}


class Planner:
    """Holds the exact tables (goal C and goal L; goal R by mirroring L)."""

    def __init__(self, verbose=False):
        t0 = time.time()
        self.tables = {g: B.ExactTables(K, goal=g, cache_dir=CACHE_DIR) for g in ('C', 'L')}
        self.hub = {g: B.HubSorter(K, home=g, tables=self.tables[g]) for g in ('C', 'L')}
        if verbose:
            print(f'[tables] ready in {time.time() - t0:.1f}s')

    # -- candidates -----------------------------------------------------------------------
    def candidates(self, deck, home):
        """(name, adjacent (src, dst) list) pairs on the physical home 'C' or 'L'."""
        out = []
        pile = A.NAMES.index(home)
        for i, path in enumerate(A.candidate_paths(tuple(deck), pile)):
            out.append((f'A{i}', [(A.NAMES[A.EDGES[j][0]], A.NAMES[A.EDGES[j][1]]) for j, _ in path]))
        hub = self.hub[home]
        _, choice = hub.plan(deck)
        out.append(('B-forward', hub.execute(deck, choice)))
        inv = inverse(deck)
        _, choice = hub.plan(inv)
        out.append(('B-inverse', time_reverse(hub.execute(inv, choice))))
        dp = MergeDP(self)
        for name, d in (('M-forward', deck), ('M-inverse', inv)):
            F = dp.solve(d)
            moves = cancel(dp.execute(d, home))
            expected = int(F[0, len(d), STACKS3.index(home), STACKS3.index(home), 0])
            assert len(moves) <= expected, (name, len(moves), expected)
            out.append((name, moves if d is deck else time_reverse(moves)))
        return out

    # -- polishing ------------------------------------------------------------------------
    def window_repair(self, deck, moves, home, kmin=1, kmax=K, solver=None, head=0, tail=0):
        """Replace windows that move kmin..kmax cards by exact optima. Returns (moves, changed).

        The first `head` and last `tail` moves are frozen (already executed) and never change.
        """
        solver = solver or self._exact
        moves = list(moves)
        changed = False
        t1 = head
        while True:
            confs, cards = B._simulate(deck, moves, home)
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
                            segs = B._top_segments(other, S)
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
        cur = {s: [rank[v] for v in segs[s]] for s in B.STACKS}
        if T.dist_code(len(order), B.encode(cur['L'], cur['C'], cur['R'])) >= length:
            return None
        new = T.walk(segs, rank)
        return [(MIRROR[s], MIRROR[d]) for s, d in new] if mirror else new

    def _exact_search(self, segs, order, X, length):
        """A* (card_sorter) for blocks too large for the tables. Same contract as _exact."""
        rank = {v: i for i, v in enumerate(order, 1)}
        packed = (bytes(rank[v] for v in reversed(segs['L'])) + b'\0'
                  + bytes(rank[v] for v in segs['C']) + b'\0'
                  + bytes(rank[v] for v in reversed(segs['R'])))
        codes = A._shortest_to_pile(packed, bytes(range(1, len(order) + 1)), A.NAMES.index(X))
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

    # -- public ---------------------------------------------------------------------------
    def plan(self, deck, start='C', report=None):
        """Verified list of card_sorter.Move records sorting `deck` (top first) back onto `start`."""
        cards = A._deck(deck)
        home = 'C' if start == 'C' else 'L'
        deck = list(cards)
        pool = []
        for name, moves in self.candidates(deck, home):
            assert B.verify(deck, moves, home)['ok'], name
            polished = self.polish_both_ways(deck, moves, home)
            if report is not None:
                report[name] = (len(moves), len(polished))
            pool.append((len(polished), name, polished))
        pool.sort(key=lambda c: c[0])
        best_name, best = pool[0][1], pool[0][2]
        for _, name, moves in pool[:3]:
            deep = self.deep_polish(deck, moves, home)
            if len(deep) < len(best):
                best_name, best = name + '+deep', deep
        if start == 'R':
            best = [(MIRROR[s], MIRROR[d]) for s, d in best]
        out = label(cards, best, start)
        cost = A.verify(cards, out, start=start)
        if len(cards) == 52:
            assert cost <= BOUND[start], (cost, best_name)
        if report is not None:
            report['best'] = best_name
        return out


    # -- scanning start (the deck order is unknown until the camera reads it) -------------
    def plan_scanned(self, deck, start='C', split=None, report=None, hold=None):
        """Plan for a machine whose camera sees only the top card of the starting compartment.

        Phase 1 (online, scan_moves): each card is read on top of the starting pile and sent
        by value: values above n - a go to pile Pb, the rest to Pt (see SCAN_SPLIT). Scanning
        stops once n - 1 cards are read, because the bottom card is then known; an already
        correct bottom card or pair never moves. From a side, cards bound for the far side
        wait on C (hold) and are only pushed on when a card bound for C is read.
        Phase 2 (full information) starts from the actual layout. Either the held cards go
        on to the far side (the certified route) or the far pile is gathered onto C on top of
        them. Then the upper block is sorted onto home and the lower block on top of it. Every
        block planner is tried (A's certified recursion, the merge DP, each forwards and
        time-reversed; B's hub DP when the layout allows), then the plan after phase 1 is
        polished. Returns verified Move records; the first len(scan_moves(...)[0]) are phase 1.
        """
        cards = A._deck(deck)
        home = 'C' if start == 'C' else 'L'
        deck = list(cards)
        n = len(deck)
        a, Pb, Pt = split or SCAN_SPLIT[home]
        a = min(a, n - 1) if n > 1 else n
        t = n - a
        split = (a, Pb, Pt)
        hold = SCAN_HOLD if hold is None else hold
        head, kept = scan_moves(deck, home, split, hold)
        active = deck[:n - kept]  # the kept bottom cards are n - kept + 1 .. n, in place
        m = len(active)
        st = B._start(deck, home)
        for x, y in head:
            st[y].append(st[x].pop())
        far = Pb if Pb != 'C' else Pt
        far_group = (lambda v: v > t) if far == Pb else (lambda v: v <= t)
        held = 0
        while held < len(st['C']) and home != 'C' and far_group(st['C'][-1 - held]):
            held += 1

        def layout(prefix):
            """Top-first contents of every stack after head + prefix."""
            cur = {x: list(v) for x, v in st.items()}
            for x, y in prefix:
                cur[y].append(cur[x].pop())
            return {x: v[::-1] for x, v in cur.items()}

        pool = []
        # Certified route: push the held cards on, then sort each pile.
        flush = [('C', far)] * held
        lay = layout(flush)
        ub = self._block_candidates(lay[Pb], Pb, home)
        lb = self._block_candidates(lay[Pt] if Pt != home else lay[Pt][:len(lay[Pt]) - kept], Pt, home)
        for un, um in ub[:2]:
            for ln, lm in lb[:2]:
                pool.append((f'{un}+{ln}', head + flush + um + lm))
        certified = len(pool[0][1])  # A's certified block plans (or better) for both piles
        if home != 'C' and far == Pb and lay[far]:
            # Gather the far pile onto C, above the held cards, and sort the upper block from C.
            gather = [(far, 'C')] * len(st[far])
            lay = layout(gather)
            k = sum(1 for v in active if v > t)
            ub = self._block_candidates(lay['C'][:k], 'C', home)
            lb = self._block_candidates(lay['C'][k:], 'C', home)
            for un, um in ub[:2]:
                for ln, lm in lb[:2]:
                    pool.append((f'gather:{un}+{ln}', head + gather + um + lm))
        if m > K and 0 < t < m and head == scan_moves(deck, home, split, False)[0]:
            hub = self.hub[home]
            _, choice = hub.plan(active)
            choice = dict(choice)
            choice[(1, m, home, 0)] = ('split', t, Pb, Pt)
            moves = hub.execute(active, choice)
            if moves[:len(head)] == head:
                pool.append(('B', moves))
        polished = []
        for name, moves in pool:
            assert B.verify(deck, moves, home)['ok'], name
            pm = self.polish_both_ways(deck, moves, home, head=len(head))
            if report is not None:
                report[name] = (len(moves), len(pm))
            polished.append((len(pm), name, pm))
        polished.sort(key=lambda c: c[0])
        best_name, best = polished[0][1], polished[0][2]
        for _, name, moves in polished[:2]:
            deep = self.deep_polish(deck, moves, home, head=len(head))
            if len(deep) < len(best):
                best_name, best = name + '+deep', deep
        assert best[:len(head)] == head and len(best) <= certified
        if start == 'R':
            best = [(MIRROR[x], MIRROR[y]) for x, y in best]
        out = label(cards, best, start)
        cost = A.verify(cards, out, start=start)
        if n == 52:
            assert cost <= BOUND[start], (cost, best_name)
        if report is not None:
            report['best'] = best_name
        return out

    def _block_candidates(self, seq, S, T):
        """(name, moves) for taking block `seq` (top first) from S to sorted on T, smallest on top.
        Moves are computed as if the block were alone (valid above frozen cards). Shortest first."""
        if not seq:
            return [('empty', [])]
        k = len(seq)
        pos = {v: i for i, v in enumerate(seq, 1)}
        back = [pos[v] for v in sorted(seq)]  # time-reversed problem: T -> S, relabelled
        ix = {'L': 0, 'C': 1, 'R': 2}
        out = []

        def a_moves(cards, s, t, mean_first, outer):
            path = A._construct(tuple(cards), tuple(sorted(cards)), ix[s], ix[t], mean_first, outer)
            return [(A.NAMES[A.EDGES[c][0]], A.NAMES[A.EDGES[c][1]]) for c, _ in A._shorten(path)]

        for mean_first in (False, True):
            for outer in (True, False):
                tag = f"A{'m' if mean_first else 'w'}{'x' if outer else ''}"
                out.append((tag, a_moves(seq, S, T, mean_first, outer)))
                if S != T or k > 1:
                    out.append((tag + 'r', time_reverse(a_moves(back, T, S, mean_first, outer))))
                if k < len(A.LEAVES):
                    break  # exact leaf: the variants are identical
            if k < len(A.LEAVES):
                break
        dp = MergeDP(self)
        dp.solve(seq)
        out.append(('M', cancel(dp.execute_block(seq, S, T))))
        dp.solve(back)
        out.append(('Mr', time_reverse(cancel(dp.execute_block(back, T, S)))))
        out = [(name, self.polish_block(seq, S, T, moves)) for name, moves in out]
        out.sort(key=lambda c: len(c[1]))
        return out

    def polish_block(self, seq, S, T, moves):
        """Cheap cancellation on an isolated block plan (full polishing runs later)."""
        return cancel(moves)

class MergeDP:
    """Per-deck optimisation over Strategy A's family (recursive position split and merge).

    A block is deck positions [i, j). It lies on stack s in deck order (top = position i) and
    must end sorted on stack t, smallest on top if o == 0 and largest on top if o == 1.
    Options:
      leaf    j - i <= K: exact table cost;
      trim    s == t and the block's deepest card is already its goal-bottom card;
      split   group 1 = [i, i+a) goes to pile u, group 2 = [i+a, j) goes to pile v, both in
              orientation 1 - o, then they merge onto t. If s != t then v = s (group 2 is sorted
              in place). Before group 2 is sorted, the leading run of group-1 merge cards goes
              to t. Group 2's last move then places its first merge card on s, and the merge
              takes it straight off again (credit -2). For s == C the group-2 plan is mirrored
              when needed to make this happen;
      across  s, t are opposite sides, v = s: group 2's first merge card goes directly to t
              and the rest is left in merge order on s (exact table cost; credit -2).
    The DP value equals the length of the executed plan.
    """

    def __init__(self, planner):
        self.P = planner

    def _dist(self, goal, cfg):
        """Exact distance from cfg {stack: top-first ranks} to ranks 0..k-1 (0 on top) on goal."""
        if goal == 'R':
            goal, cfg = 'L', {MIRROR[s]: v for s, v in cfg.items()}
        k = sum(len(v) for v in cfg.values())
        if k == 0:
            return 0
        return self.P.tables[goal].dist_code(k, B.encode(cfg.get('L', []), cfg.get('C', []), cfg.get('R', [])))

    def solve(self, deck):
        import numpy as np
        n = len(deck)
        self.deck = deck
        self._memo = {}
        INF = 10 ** 6
        F = np.full((n + 1, n + 1, 3, 3, 2), INF, dtype=np.int64)
        how = {}
        idx = {'L': 0, 'C': 1, 'R': 2}
        dist = [[abs(x - y) for y in range(3)] for x in range(3)]
        for i in range(n + 1):
            F[i, i] = 0
        for length in range(1, n + 1):
            for i in range(0, n - length + 1):
                j = i + length
                block = deck[i:j]
                srt = sorted(block)
                for o in (0, 1):
                    goal_order = srt if o == 0 else srt[::-1]  # top first on t
                    if length <= K:
                        rank = {v: r for r, v in enumerate(goal_order)}
                        ranks = [rank[v] for v in block]
                        for S in STACKS3:
                            for T in STACKS3:
                                F[i, j, idx[S], idx[T], o] = self._dist(T, {S: ranks})
                                how[i, j, S, T, o] = ('leaf',)
                        continue
                    a = np.arange(1, length)
                    b = length - a
                    # The first merge card is in group 1 exactly when a > its position.
                    first_in_g1 = a > block.index(goal_order[-1])
                    for S in STACKS3:
                        s = idx[S]
                        for T in STACKS3:
                            t = idx[T]
                            best, bh = INF, None
                            if S == T and block[-1] == goal_order[-1]:
                                best, bh = int(F[i, j - 1, s, t, o]), ('trim',)
                            if S != T:
                                pairs = [(3 - s - t, s)]
                            else:
                                pairs = [(x, 3 - s - x) for x in range(3) if x != s]
                            for u, v in pairs:
                                f1 = F[i, i + a, s, u, 1 - o]
                                f2 = F[i + a, j, s, v, 1 - o]
                                cost = f1 + f2 + a * dist[u][t] + b * dist[v][t]
                                if S != T:
                                    cost = cost - 2 * (f2 > 0)
                                    if u != 1:
                                        # Group 1's last move put the first merge card on side
                                        # pile u, coming from C; the pre-merge move u -> C undoes it.
                                        cost = cost - 2 * ((f1 > 0) & first_in_g1)
                                elif v != 1:
                                    # Group 2's last move put the first merge card on side pile v,
                                    # coming from C; the merge's first move v -> C undoes it.
                                    cost = cost - 2 * ((f2 > 0) & ~first_in_g1)
                                k = int(np.argmin(cost))
                                if cost[k] < best:
                                    best, bh = int(cost[k]), ('split', int(a[k]), STACKS3[u], STACKS3[v], False)
                                if S != T and dist[s][t] == 2:
                                    for aa in range(max(1, length - K), length):
                                        c = (int(F[i, i + aa, s, u, 1 - o]) + self._across(i + aa, j, S, o)
                                             + aa * dist[u][t] + (length - aa) * dist[v][t] - 2)
                                        if c < best:
                                            best, bh = c, ('split', aa, STACKS3[u], STACKS3[v], True)
                            F[i, j, s, t, o] = best
                            how[i, j, S, T, o] = bh
        self.F, self.how = F, how
        return F

    def _across_target(self, i, j, S, o):
        """Group 2 = positions [i, j) on S (a side). The merge feed is the block's values ordered
        bottom-first of the parent goal (orientation o). Returns (near pile top-first, far card)."""
        vals = sorted(self.deck[i:j], reverse=(o == 0))  # parent feed order
        return vals[1:], vals[0]

    def _across(self, i, j, S, o):
        key = (i, j, S, o)
        if key not in self._memo:
            self._memo[key] = self._across_cost(i, j, S, o)
        return self._memo[key]

    def _across_cost(self, i, j, S, o):
        near, far = self._across_target(i, j, S, o)
        rank = {v: r for r, v in enumerate(self.deck[i:j])}  # start order = goal (sorted on S)
        cfg = {S: [rank[v] for v in near], MIRROR[S]: [rank[far]]}
        return self._dist(S, cfg)

    def execute(self, deck, home):
        """Moves for the solved deck, starting on home and ending sorted on home."""
        return self.execute_block(deck, home, home)

    def execute_block(self, deck, S, T):
        """Moves (as if alone) taking the solved sequence `deck` (top first) from S to sorted
        on T, smallest on top. By the projection lemma they stay valid above frozen cards."""
        n = len(deck)
        st = {x: [] for x in STACKS3}
        st[S] = list(reversed(deck))
        moves = []

        def go(x, y, mir):
            x, y = (MIRROR[x], MIRROR[y]) if mir else (x, y)
            for p, q in B.route(x, y):
                st[q].append(st[p].pop())
                moves.append((p, q))

        def phys(x, mir):
            return MIRROR[x] if mir else x

        def walk_to(goal, cards_top_first, block, mir):
            """Exact moves bringing `block` (on top segments) to `cards_top_first` on goal."""
            segs = B._top_segments(st, set(block))
            assert sum(len(v) for v in segs.values()) == len(block)
            rank = {v: r for r, v in enumerate(cards_top_first)}
            if mir:  # walk in the mirrored world so the path really is mirrored
                segs = {MIRROR[x]: v for x, v in segs.items()}
            path = self._walk(goal, segs, rank)
            if mir:
                path = [(MIRROR[p], MIRROR[q]) for p, q in path]
            for p, q in path:
                st[q].append(st[p].pop())
                moves.append((p, q))

        def run(i, j, S, T, o, mir):
            if i >= j:
                return
            ch = self.how[i, j, S, T, o]
            block = deck[i:j]
            srt = sorted(block)
            goal_order = srt if o == 0 else srt[::-1]
            if ch[0] == 'leaf':
                walk_to(T, goal_order, block, mir)
                return
            if ch[0] == 'trim':
                run(i, j - 1, S, T, o, mir)
                return
            _, a, U, V, across = ch
            feed = goal_order[::-1]
            g1 = set(deck[i:i + a])
            run(i, i + a, S, U, 1 - o, mir)
            cut = 0
            if S != T:
                while feed[cut] in g1:
                    go(U, T, mir)
                    cut += 1
            if across:
                near, far = self._across_target(i + a, j, S, o)
                self._play_across(st, moves, deck[i + a:j], near, far, phys(S, mir))
                cut += 1
            else:
                start = len(moves)
                snapshot = {x: list(y) for x, y in st.items()}
                run(i + a, j, S, V, 1 - o, mir)
                if S == 'C' and S != T and len(moves) > start:
                    if moves[-1][0] != phys(T, mir):
                        del moves[start:]
                        st.clear()
                        st.update(snapshot)
                        run(i + a, j, S, V, 1 - o, not mir)
            for card in feed[cut:]:
                go(U if card in g1 else V, T, mir)

        run(0, n, S, T, 0, False)
        return moves

    def _walk(self, G, segs, rank):
        if G == 'R':
            new = self.P.tables['L'].walk({MIRROR[s]: v for s, v in segs.items()}, rank)
            return [(MIRROR[s], MIRROR[d]) for s, d in new]
        return self.P.tables[G].walk(segs, rank)

    def _play_across(self, st, moves, cards, near, far, S):
        rank = {v: r for r, v in enumerate(cards)}
        segs = {x: [] for x in STACKS3}
        segs[S] = list(near)
        segs[MIRROR[S]] = [far]
        back = self._walk(S, segs, rank)  # from the target configuration to the start
        for p, q in [INVERSE[x] for x in reversed(back)]:
            st[q].append(st[p].pop())
            moves.append((p, q))


STACKS3 = ('L', 'C', 'R')


# Phase-1 split for a scanning start: (a, Pb, Pt). The a largest values go to Pb, the rest
# to Pt. Each option keeps the certified bound (322 centre, 350 side); see scan_bound().
SCAN_SPLIT = {'C': (30, 'R', 'L'), 'L': (21, 'R', 'C')}
# From a side, far-bound cards wait on C until a C-bound card is read (see scan_moves).
SCAN_HOLD = True


def scan_destination(value, home, n=52, split=None):
    """Where a card goes once the camera has read it on top of C (physical home C or L)."""
    a, Pb, Pt = split or SCAN_SPLIT[home]
    return Pb if value > n - a else Pt


def scan_kept(deck, home=None):
    """Bottom cards the scan leaves in place. The camera reads the top of the starting pile,
    so n - 1 cards must be read; the bottom card is then known by elimination. The last card
    read is still on the pile, so a correct bottom pair can stay."""
    n = len(deck)
    kept = 0
    while kept < min(n, 2) and deck[n - 1 - kept] == n - kept:
        kept += 1
    return kept


def scan_moves(deck, home, split=None, hold=True):
    """(phase-1 moves, kept) on the physical home C or L.

    Each card is read on top of the home pile before it moves, then routed by value. From a
    side with hold=True, a card bound for the far side moves to C and waits there; waiting
    cards are pushed on to the far side only when a card bound for C is read. Cards still
    waiting at the end stay on C (phase 2 decides). The `kept` bottom cards never move."""
    kept = scan_kept(deck, home)
    moves = []
    held = 0
    for v in deck[:len(deck) - kept]:
        dest = scan_destination(v, home, len(deck), split)
        if home == 'C':
            moves.append(('C', dest))
        elif dest == 'C':
            moves += [('C', MIRROR[home])] * held + [(home, 'C')]
            held = 0
        elif hold:
            moves.append((home, 'C'))
            held += 1
        else:
            moves += [(home, 'C'), ('C', dest)]
    return moves, kept


def scan_bound(n=52, home='C', split=None):
    """Certified worst case for plan_scanned: the scan moves plus the best of A's and B's
    worst-case block bounds for each pile."""
    a, Pb, Pt = split or SCAN_SPLIT[home]
    ix = {'L': 0, 'C': 1, 'R': 2}
    V, _ = B.worst_case_table(n, get_planner().tables[home].worst_cases(), home)

    def block(k, s):
        return min(A._bound(k, ix[s], ix[home], False, True)[0], V[s][k]) if k else 0
    return a * B.dcost(home, Pb) + (n - a) * B.dcost(home, Pt) + block(a, Pb) + block(n - a, Pt)


def inverse(deck):
    inv = [0] * len(deck)
    for i, v in enumerate(deck):
        inv[v - 1] = i + 1
    return inv


def time_reverse(moves):
    return [(d, s) for s, d in reversed(moves)]


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
    """hubsort.remove_pointless_excursions, restricted to moves outside the frozen ends.

    Delete c: X->Y (time i) ... c: Y->X (time j) when, in between, stack X never drops below
    the level it had without c and is back at exactly that level at time j.
    """
    moves = list(moves)
    idx = {'L': 0, 'C': 1, 'R': 2}
    while True:
        st = B._start(deck, home)
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


def label(deck, moves, start):
    st = B._start(list(deck), start)
    out = []
    for s, d in moves:
        st[d].append(st[s].pop())
        out.append(A.Move(s, d, st[d][-1]))
    return out


_PLANNER = None


def get_planner():
    global _PLANNER
    if _PLANNER is None:
        _PLANNER = Planner()
    return _PLANNER


def plan(deck, *, start='C'):
    """Shortest verified plan found by the combined planner. Same output type as card_sorter.plan."""
    if start not in ('L', 'C', 'R'):
        raise ValueError('The starting and finishing pile must be L, C, or R.')
    return get_planner().plan(deck, start)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cards', type=int, nargs='*', help='deck from top to bottom')
    ap.add_argument('--start', choices=('L', 'C', 'R'), default='C')
    ap.add_argument('--seed', type=int)
    ap.add_argument('--show-moves', action='store_true')
    args = ap.parse_args()
    cards = args.cards
    if args.seed is not None:
        cards = list(range(1, 53))
        random.Random(args.seed).shuffle(cards)
    if not cards:
        ap.error('supply a deck (top first) or --seed')
    report = {}
    moves = get_planner().plan(cards, args.start, report)
    print(f'Top first in {args.start}:', ' '.join(map(str, cards)))
    for name, value in report.items():
        if name == 'best':
            continue
        raw, pol = value
        print(f'  {name:10s} {raw:4d} -> {pol:4d} after polishing')
    print(f'Verified adjacent transfers: {len(moves)} (best: {report["best"]})')
    if args.show_moves:
        for i, (s, t, card) in enumerate(moves, 1):
            print(f'{i:3d}  {s} -> {t}  card {card}')


if __name__ == '__main__':
    main()
