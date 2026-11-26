"""Per-deck dynamic programme over Strategy A's family (recursive position split and merge).

Strategy A fixes its split points in advance to get a worst-case certificate. MergeDP picks
them per deck, using exact 9-card table leaves and the cancellations that are guaranteed to
happen, so it usually finds a shorter plan in the same family.
"""

import numpy as np

from .model import INVERSE, MIRROR, STACKS, route
from .tables import K, encode, top_segments


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

    def __init__(self, tables):
        """`tables`: {'C': ExactTables, 'L': ExactTables} (goal R by mirroring L)."""
        self.tables = tables

    def _dist(self, goal, cfg):
        """Exact distance from cfg {stack: top-first ranks} to ranks 0..k-1 (0 on top) on goal."""
        if goal == 'R':
            goal, cfg = 'L', {MIRROR[s]: v for s, v in cfg.items()}
        k = sum(len(v) for v in cfg.values())
        if k == 0:
            return 0
        return self.tables[goal].dist_code(k, encode(cfg.get('L', []), cfg.get('C', []), cfg.get('R', [])))

    def solve(self, deck):
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
                        for S in STACKS:
                            for T in STACKS:
                                F[i, j, idx[S], idx[T], o] = self._dist(T, {S: ranks})
                                how[i, j, S, T, o] = ('leaf',)
                        continue
                    a = np.arange(1, length)
                    b = length - a
                    # The first merge card is in group 1 exactly when a > its position.
                    first_in_g1 = a > block.index(goal_order[-1])
                    for S in STACKS:
                        s = idx[S]
                        for T in STACKS:
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
                                    best, bh = int(cost[k]), ('split', int(a[k]), STACKS[u], STACKS[v], False)
                                if S != T and dist[s][t] == 2:
                                    for aa in range(max(1, length - K), length):
                                        c = (int(F[i, i + aa, s, u, 1 - o]) + self._across(i + aa, j, S, o)
                                             + aa * dist[u][t] + (length - aa) * dist[v][t] - 2)
                                        if c < best:
                                            best, bh = c, ('split', aa, STACKS[u], STACKS[v], True)
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
        st = {x: [] for x in STACKS}
        st[S] = list(reversed(deck))
        moves = []

        def go(x, y, mir):
            x, y = (MIRROR[x], MIRROR[y]) if mir else (x, y)
            for p, q in route(x, y):
                st[q].append(st[p].pop())
                moves.append((p, q))

        def phys(x, mir):
            return MIRROR[x] if mir else x

        def walk_to(goal, cards_top_first, block, mir):
            """Exact moves bringing `block` (on top segments) to `cards_top_first` on goal."""
            segs = top_segments(st, set(block))
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
            new = self.tables['L'].walk({MIRROR[s]: v for s, v in segs.items()}, rank)
            return [(MIRROR[s], MIRROR[d]) for s, d in new]
        return self.tables[G].walk(segs, rank)

    def _play_across(self, st, moves, cards, near, far, S):
        rank = {v: r for r, v in enumerate(cards)}
        segs = {x: [] for x in STACKS}
        segs[S] = list(near)
        segs[MIRROR[S]] = [far]
        back = self._walk(S, segs, rank)  # from the target configuration to the start
        for p, q in [INVERSE[x] for x in reversed(back)]:
            st[q].append(st[p].pop())
            moves.append((p, q))
