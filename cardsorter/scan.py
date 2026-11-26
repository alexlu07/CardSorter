"""Phase 1 rules for a scanning start, shared by the dealer (hardware) and the planner.

The camera reads only the top card of the starting compartment, so every card is routed by
value at the moment it is read, using only that card:

  from C:     values above n - a go to Pb, the rest to Pt (SCAN_SPLIT);
  from a side (planned as L; R is its mirror image): cards for C move there; cards for the
              far side move to C and wait (SCAN_HOLD), and move on only when a card bound
              for C is read. Cards still waiting at the end are left for phase 2.

Scanning stops once n - 1 cards are read: the bottom card is then known by elimination, and a
bottom card or pair that is already in its final place never moves.
"""

from . import strategy_a as A
from .model import MIRROR, dist
from .strategy_b import worst_case_table

# (a, Pb, Pt): the a largest values go to Pb, the rest to Pt. Each keeps the certified
# bound (322 from C, 350 from a side); see scan_bound().
SCAN_SPLIT = {'C': (30, 'R', 'L'), 'L': (21, 'R', 'C')}
# From a side, far-bound cards wait on C until a C-bound card is read.
SCAN_HOLD = True


def scan_destination(value, home, n=52, split=None):
    """Where a card goes once the camera has read it (physical home C or L)."""
    a, Pb, Pt = split or SCAN_SPLIT[home]
    return Pb if value > n - a else Pt


def scan_kept(deck, home=None):
    """Bottom cards the scan leaves in place. n - 1 cards must be read; the bottom card is
    then known by elimination. The last card read is still on the pile, so a correct bottom
    pair can stay."""
    n = len(deck)
    kept = 0
    while kept < min(n, 2) and deck[n - 1 - kept] == n - kept:
        kept += 1
    return kept


def scan_moves(deck, home, split=None, hold=True):
    """(phase-1 moves, kept) on the physical home C or L. The `kept` bottom cards never move."""
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


def scan_bound(n=52, home='C', split=None, tables=None):
    """Certified worst case for Planner.plan_scanned: the scan moves plus the better of A's
    and B's worst-case block bounds for each pile."""
    if tables is None:
        from .planner import get_planner
        tables = get_planner().tables
    a, Pb, Pt = split or SCAN_SPLIT[home]
    ix = {'L': 0, 'C': 1, 'R': 2}
    V, _ = worst_case_table(n, tables[home].worst_cases(), home)

    def block(k, s):
        return min(A.bound(k, ix[s], ix[home], False, True)[0], V[s][k]) if k else 0
    return a * dist(home, Pb) + (n - a) * dist(home, Pt) + block(a, Pb) + block(n - a, Pt)
