"""The planner: candidate plans from every strategy, polished, verified, the shortest kept.

Planner.plan_scanned(deck, start) is what the machine uses. Its camera reads only the top of
the starting pile, so phase 1 routes each card by value as it is read (scan.py); phase 2 plans
the rest from the known layout. Planner.plan(deck, start) assumes the whole order is known in
advance. Both keep the certified bounds: at most 322 moves from C and 350 from a side.

Candidates come from Strategy A's certified recursion (strategy_a), Strategy B's per-deck hub
distribution (strategy_b) and the per-deck merge DP (merge_dp), each also on the inverse deck
played time-reversed. Every candidate is polished (polish), replayed by model.verify and
checked against the bound.
"""

from . import strategy_a as A
from .merge_dp import MergeDP
from .model import MIRROR, STACKS, check_deck, inverse, label, letter, piles, sorts, time_reverse, verify
from .polish import Polisher, cancel
from .scan import SCAN_HOLD, SCAN_SPLIT, scan_moves
from .strategy_b import HubSorter
from .tables import K, load_tables

BOUND = {'C': 322, 'L': 350, 'R': 350}


class Planner:
    """Holds the exact tables (goal C and goal L; goal R by mirroring L) and the planners."""

    def __init__(self, tables=None):
        self.tables = tables if tables is not None else load_tables()
        self.hub = {g: HubSorter(self.tables[g]) for g in ('C', 'L')}
        self.polisher = Polisher(self.tables)

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
        dp = MergeDP(self.tables)
        for name, d in (('M-forward', deck), ('M-inverse', inv)):
            F = dp.solve(d)
            moves = cancel(dp.execute(d, home))
            expected = int(F[0, len(d), STACKS.index(home), STACKS.index(home), 0])
            assert len(moves) <= expected, (name, len(moves), expected)
            out.append((name, moves if d is deck else time_reverse(moves)))
        return out

    def plan(self, deck, start='C', report=None):
        """Full-knowledge plan: verified Move records sorting `deck` (top first) back onto `start`."""
        cards = check_deck(deck)
        home = 'C' if start == 'C' else 'L'
        deck = list(cards)
        pool = []
        for name, moves in self.candidates(deck, home):
            assert sorts(deck, moves, home), name
            polished = self.polisher.polish_both_ways(deck, moves, home)
            if report is not None:
                report[name] = (len(moves), len(polished))
            pool.append((len(polished), name, polished))
        pool.sort(key=lambda c: c[0])
        best_name, best = pool[0][1], pool[0][2]
        for _, name, moves in pool[:3]:
            deep = self.polisher.deep_polish(deck, moves, home)
            if len(deep) < len(best):
                best_name, best = name + '+deep', deep
        if start == 'R':
            best = [(MIRROR[s], MIRROR[d]) for s, d in best]
        out = label(cards, best, start)
        cost = verify(cards, out, start=start)
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
        cards = check_deck(deck)
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
        st = piles(deck, home)
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
            assert sorts(deck, moves, home), name
            pm = self.polisher.polish_both_ways(deck, moves, home, head=len(head))
            if report is not None:
                report[name] = (len(moves), len(pm))
            polished.append((len(pm), name, pm))
        polished.sort(key=lambda c: c[0])
        best_name, best = polished[0][1], polished[0][2]
        for _, name, moves in polished[:2]:
            deep = self.polisher.deep_polish(deck, moves, home, head=len(head))
            if len(deep) < len(best):
                best_name, best = name + '+deep', deep
        assert best[:len(head)] == head and len(best) <= certified
        if start == 'R':
            best = [(MIRROR[x], MIRROR[y]) for x, y in best]
        out = label(cards, best, start)
        cost = verify(cards, out, start=start)
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
            path = A.construct(tuple(cards), tuple(sorted(cards)), ix[s], ix[t], mean_first, outer)
            return [(A.NAMES[A.EDGES[c][0]], A.NAMES[A.EDGES[c][1]]) for c, _ in A.shorten(path)]

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
        dp = MergeDP(self.tables)
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


_PLANNER = None


def get_planner():
    """The shared Planner. The first call loads (or builds) the exact tables."""
    global _PLANNER
    if _PLANNER is None:
        _PLANNER = Planner()
    return _PLANNER


def plan_scanned(deck, *, start='C'):
    """Scan-first plan for the machine: Move records, the first ones being the scan moves."""
    return get_planner().plan_scanned(deck, letter(start))


def plan(deck, *, start='C'):
    """Full-knowledge plan when the whole order is known in advance."""
    return get_planner().plan(deck, letter(start))
