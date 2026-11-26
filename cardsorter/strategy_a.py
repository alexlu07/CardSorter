"""Strategy A: certified recursive block merge (splits blocks by position, then merges).

Blocks of up to 11 cards are solved exactly (A* with additive pattern databases); larger
blocks split into a top group and a remainder, sort each onto its own pile, and merge.
bounds() gives the certified worst case: 322 moves from C, 350 from a side. The small-block
constants in LEAVES and ONE_CARD_ACROSS can be reproduced with tools/certify_blocks.cpp.

Internally stacks are indices L=0, C=1, R=2 and moves are (edge code, card) pairs; plan()
returns model.Move records.
"""

import heapq
import random
from bisect import bisect_left
from collections import deque
from fractions import Fraction
from functools import cache, lru_cache
from itertools import product
from math import factorial

from .model import Move, check_deck, letter, verify

L, C, R = range(3)
NAMES = "LCR"
EDGES = ((C, L), (L, C), (C, R), (R, C))
CODE = {edge: code for code, edge in enumerate(EDGES)}


def _starting_pile(start):
    return NAMES.index(letter(start))


# For each size: CC, CO, OO (same outer), LR (opposite outers). Each tuple is
# (maximum shortest distance, sum of shortest distances over all n! orders).
# These finite BFS results can be reproduced with tools/certify_blocks.cpp.
LEAVES = (
    ((0, 0), (0, 0), (0, 0), (0, 0)),  # empty
    ((0, 0), (1, 1), (0, 0), (2, 2)),
    ((4, 4), (4, 6), (6, 6), (4, 8)),
    ((8, 30), (7, 32), (10, 40), (8, 38)),
    ((12, 194), (12, 192), (14, 248), (12, 214)),
    ((16, 1332), (15, 1312), (18, 1662), (16, 1406)),
    ((20, 10162), (20, 10124), (22, 12458), (20, 10596)),
    ((24, 86624), (23, 87458), (26, 104650), (24, 90234)),
    ((28, 820682), (28, 838138), (30, 978600), (28, 857362)),
    ((32, 8574602), (31, 8834958), (34, 10103678), (34, 8993826)),
    ((36, 98033786), (36, 101668270), (38, 114281638), (38, 103250874)),
    ((40, 1217838156), (41, 1268763200), (42, 1406192256), (44, 1287648452)),
)

# Starting on one outer pile, finish with one specified card on the opposite
# pile and every other card in a specified order on the starting pile.
# Each pair contains the maximum and sum of distances over all n! orders.
ONE_CARD_ACROSS = (
    (0, 0), (2, 2), (4, 6), (8, 36), (12, 222), (16, 1516),
    (20, 11550), (24, 98246), (28, 927600), (32, 9649664),
    (36, 109800310), (42, 1357496432),
)


def _endpoint_type(source, dest):
    if source == dest:
        return 0 if source == C else 2
    return 1 if C in (source, dest) else 3


@cache
def bound(n, source, dest, mean_first=False, use_outer_split=False):
    """Return (worst-case ceiling, uniform-mean ceiling, chosen split)."""
    if n < len(LEAVES):
        maximum, total = LEAVES[n][_endpoint_type(source, dest)]
        return maximum, Fraction(total, factorial(n)), None
    best = None
    best_key = None
    for backward in (False, True):
        s, t = (dest, source) if backward else (source, dest)
        for u in range(3):
            if u in (s, t):
                continue
            v = 3 - t - u
            for a in range(1, n):
                b = n - a
                first, ef, _ = bound(a, s, u, mean_first, use_outer_split)
                second, es, _ = bound(b, s, v, mean_first, use_outer_split)
                merge = a * abs(u - t) + b * abs(v - t)
                worst_saving = 2 if s != t and b >= 2 else 0
                mean_saving = Fraction(0)
                if s != t:
                    mean_saving = 2 * (1 - Fraction(1, factorial(b)))
                    if u != C:
                        mean_saving += Fraction(2 * a, n)
                elif v != C:
                    mean_saving = Fraction(2 * b, n)
                choices = [(first + second + merge - worst_saving,
                            ef + es + merge - mean_saving, (backward, u, a, False))]
                if use_outer_split and abs(s - t) == 2 and b < len(ONE_CARD_ACROSS):
                    # The first card wanted from the second group lands directly
                    # at t, incorporating two units of the merge into this search.
                    maximum, total = ONE_CARD_ACROSS[b]
                    choices.append((first + maximum + merge - 2,
                                    ef + Fraction(total, factorial(b)) + merge - 2,
                                    (backward, u, a, True)))
                for candidate in choices:
                    w, e, split = candidate
                    key = (e, w, split) if mean_first else candidate
                    if best_key is None or key < best_key:
                        best, best_key = candidate, key
    return best


def bounds(n=52, *, start="C"):
    """Proven worst-case and uniform-mean ceilings, in adjacent transfers."""
    if type(n) is not int or not 1 <= n <= 52:
        raise ValueError("Expected a deck size from 1 through 52.")
    pile = C if _starting_pile(start) == C else L
    worst = bound(n, pile, pile, use_outer_split=True)[0]
    mean = bound(n, pile, pile, mean_first=True, use_outer_split=True)[1]
    return worst, mean


def _active(cards):
    m = len(cards)
    while m and cards[m-1] == m:
        m -= 1
    return cards[:m]


def _two_chains(cards):
    """Return an outer-pile assignment for two increasing chains, if possible."""
    ends = {L: 0, R: 0}
    assignment = {}
    for x in cards:
        choices = [p for p in (L, R) if ends[p] < x]
        if not choices:
            return None
        pile = max(choices, key=ends.get)
        ends[pile] = x
        assignment[x] = pile
    return assignment


def movement_lower_bound(deck, *, start="C"):
    """Per-deck lower bound for the selected starting and finishing pile."""
    cards = _active(check_deck(deck))
    if _starting_pile(start) != C:
        # Cards that never visit the far pile keep their relative order.
        tails = []
        for x in cards:
            index = bisect_left(tails, x)
            if index == len(tails):
                tails.append(x)
            else:
                tails[index] = x
        return 4 * len(cards) - 2 * len(tails)
    # State = sorted pair of last ranks of the two retained subsequences.
    best = {(0, 0): 0}
    for x in cards:
        after = best.copy()  # skip x
        for (a, b), count in best.items():
            if a < x:
                key = (min(b, x), max(b, x))
                after[key] = max(after.get(key, 0), count + 1)
            if b < x:
                key = (a, x)
                after[key] = max(after.get(key, 0), count + 1)
        best = after
    return 4 * len(cards) - 2 * max(best.values())


# Search state: L bottom-first, zero, C top-first, zero, R bottom-first.
# Moving through a separator always transfers one accessible top card.
def _packed(cards, pile):
    data = bytes(cards)
    if pile == C:
        return b"\0" + data + b"\0"
    if pile == L:
        return data[::-1] + b"\0\0"
    return b"\0\0" + data[::-1]


def _neighbors(state):
    i = state.index(0)
    if state[i + 1]:
        top, rest = state[i+1:i+2], state[i+2:]
        yield 0, state[:i] + top + b"\0" + rest
        yield 2, state[:i+1] + rest + top
    if i:
        yield 1, state[:i-1] + b"\0" + state[i-1:i] + state[i+1:]
    if state[-1]:
        yield 3, state[:i+1] + state[-1:] + state[i+1:-1]


@cache
def _pattern_distances(n, dest):
    goal = _packed(range(1, n + 1), dest)
    dist = {goal: 0}
    todo = deque([goal])
    while todo:
        state = todo.popleft()
        nd = dist[state] + 1
        for _, neighbor in _neighbors(state):
            if neighbor not in dist:
                dist[neighbor] = nd
                todo.append(neighbor)
    return dist


def _pattern_partitions(order, dest, start):
    """Build several disjoint pattern sums and retain the strongest at the start."""
    n = len(order)
    labels = list(range(1, n + 1))
    group_count = (n + 5) // 6
    width, extra = divmod(n, group_count)
    orders = [labels, list(order), labels[::2] + labels[1::2], list(order[::2] + order[1::2])]
    rng = random.Random(n)  # reproducible disk-free search heuristic
    for _ in range(8):
        orders.append(rng.sample(labels, n))
    candidates = {}
    for perm in orders:
        groups = []
        pos = 0
        for j in range(group_count):
            end = pos + width + (j < extra)
            groups.append(tuple(sorted(perm[pos:end])))
            pos = end
        key = tuple(sorted(groups))
        if key in candidates:
            continue
        parts = []
        score = 0
        for group in key:
            table = bytes.maketrans(bytes(group), bytes(range(1, len(group) + 1)))
            drop = bytes(x for x in labels if x not in group)
            distances = _pattern_distances(len(group), dest)
            parts.append((table, drop, distances))
            score += distances[start.translate(table, drop)]
        candidates[key] = score, parts
    ranked = sorted(candidates.values(), key=lambda p: p[0], reverse=True)
    return [parts for _, parts in ranked[:4]]


@lru_cache(maxsize=4096)
def shortest_to_pile(start, order, dest):
    """A* from a packed state to an ordered pile. Returns adjacent edge codes."""
    n = len(order)
    goal = _packed(range(1, n + 1), dest)
    if start == goal:
        return ()
    if n <= 6:
        dist = _pattern_distances(n, dest)
        state = start
        codes = []
        while state != goal:
            code, state = next((j, v) for j, v in _neighbors(state) if dist[v] == dist[state] - 1)
            codes.append(code)
        return tuple(codes)

    partitions = _pattern_partitions(order, dest, start)

    def estimate(state):
        return max(sum(d[state.translate(table, drop)] for table, drop, d in parts)
                   for parts in partitions)

    # Store the arrival edge. An inverse move reconstructs the parent exactly.
    records = {start: (0, -1)}
    queue = [(estimate(start), 0, start)]
    while queue:
        _, neg_g, state = heapq.heappop(queue)
        g = -neg_g
        if records[state][0] != g:
            continue
        if state == goal:
            break
        last = records[state][1]
        for code, nxt in _neighbors(state):
            if code == (last ^ 1):
                continue
            ng = g + 1
            prior = records.get(nxt)
            if prior is None or ng < prior[0]:
                records[nxt] = ng, code
                heapq.heappush(queue, (ng + estimate(nxt), -ng, nxt))
    else:
        raise RuntimeError("Goal unreachable.")
    path = []
    state = goal
    while state != start:
        code = records[state][1]
        path.append(code)
        state = next(v for j, v in _neighbors(state) if j == (code ^ 1))
    return tuple(reversed(path))


def _transfer(source, dest, card):
    if abs(source - dest) == 2:
        return [(CODE[source, C], card), (CODE[C, dest], card)]
    return [(CODE[source, dest], card)]


def _reverse(moves):
    return [(code ^ 1, card) for code, card in reversed(moves)]


def _exact_block(cards, target, source, dest):
    if source == dest:
        m = len(cards)
        while m and cards[m-1] == target[m-1]:
            m -= 1
        cards, target = cards[:m], target[:m]
    if not cards:
        return []
    if source != dest and cards == target[::-1]:
        return [step for card in cards for step in _transfer(source, dest, card)]
    ranks = {card: k for k, card in enumerate(target, 1)}
    order = bytes(ranks[x] for x in cards)
    codes = shortest_to_pile(_packed(order, source), order, dest)
    return _label_path(cards, source, codes)


def _one_card_across(cards, target, source):
    """Put target[0] on the opposite outer pile and target[1:] back on source."""
    ranks = {card: k for k, card in enumerate(cards, 1)}
    order = bytes(ranks[x] for x in target)
    near, far = order[1:][::-1], order[:1]
    left, right = (near, far) if source == L else (far, near)
    # Search backward to an ordinary ordered pile so the same pattern
    # databases apply. Both outer piles are packed bottom first.
    backward = shortest_to_pile(left + b"\0\0" + right, order, source)
    return _label_path(cards, source, (j ^ 1 for j in reversed(backward)))


def _label_path(cards, source, codes):
    stacks = [[], [], []]
    stacks[source] = list(reversed(cards))
    result = []
    for code in codes:
        s, t = EDGES[code]
        card = stacks[s].pop()
        stacks[t].append(card)
        result.append((code, card))
    return result


def construct(cards, target, source, dest, mean_first=False, use_outer_split=False):
    n = len(cards)
    if n < len(LEAVES):
        return _exact_block(cards, target, source, dest)
    if source == dest and cards == target:
        return []
    backward, u, a, across = bound(n, source, dest, mean_first, use_outer_split)[2]
    if backward:
        cards, target = target, cards
        source, dest = dest, source
    v = 3 - dest - u
    group = set(cards[:a])
    feed = target[::-1]
    first_goal = tuple(x for x in feed if x in group)
    second_goal = tuple(x for x in feed if x not in group)
    path = construct(cards[:a], first_goal, source, u, mean_first, use_outer_split)
    # On a transfer to another pile, put the initial run of first-group
    # merge cards at the destination before starting the second subproblem.
    cut = next(i for i, x in enumerate(feed) if x not in group) if source != dest else 0
    for card in feed[:cut]:
        path.extend(_transfer(u, dest, card))
    if across:
        second_path = _one_card_across(cards[a:], second_goal, source)
        cut += 1  # This merge card is already on the destination.
    else:
        second_path = construct(cards[a:], second_goal, source, v, mean_first, use_outer_split)
    if source == C and source != dest and second_path:
        # This child starts and finishes on C. Its two outer buffers are
        # interchangeable above their frozen bases. Match its last edge to
        # the next (outgoing) edge, so the two cancel.
        if EDGES[second_path[-1][0]][0] != dest:
            second_path = [(code ^ 2, card) for code, card in second_path]
    path.extend(second_path)
    for card in feed[cut:]:
        path.extend(_transfer(u if card in group else v, dest, card))
    path = shorten(path)
    return _reverse(path) if backward else path


def shorten(path, m=52):
    # Projection freezes the correct bottom suffix. Cancel adjacent inverse moves.
    out = []
    for code, card in path:
        if card > m:
            continue
        if out and out[-1] == (code ^ 1, card):
            out.pop()
        else:
            out.append((code, card))
    return out


def _easy(cards):
    if not cards:
        return []
    assign = _two_chains(cards)
    if assign is not None:
        return ([(CODE[C, assign[x]], x) for x in cards]
                + [(CODE[assign[x], C], x) for x in range(len(cards), 0, -1)])
    if all(x == len(cards) - i for i, x in enumerate(cards)):
        # Expose the first card at the bottom of L, then rebuild C.
        path = [(CODE[C, L], x) for x in cards[:-1]]
        path.append((CODE[C, R], cards[-1]))
        for x in reversed(cards[1:-1]):
            path.extend(_transfer(L, R, x))
        path.append((CODE[L, C], cards[0]))
        path.extend((CODE[R, C], x) for x in cards[1:])
        return path
    return None


def _side_pass(cards, target):
    """Empty L into C, then rebuild L using R as a temporary stack if possible."""
    path = [(CODE[L, C], x) for x in cards]
    center = list(cards)  # top at the end, after the initial transfer
    far = []
    for x in reversed(target):
        if far and far[-1] == x:
            far.pop()
            path.extend(_transfer(R, L, x))
        else:
            while center and center[-1] != x:
                card = center.pop()
                far.append(card)
                path.append((CODE[C, R], card))
            if not center:
                return None
            center.pop()
            path.append((CODE[C, L], x))
    return shorten(path)


def plan(deck, *, start="C", exact=False):
    """Generate adjacent Move records that sort the deck back into start (L, C, R).

    exact=True is optimal on every completed search. General 52-card exact searches
    can exhaust available time or memory. The default uses the certified construction.
    """
    cards = check_deck(deck)
    requested = _starting_pile(start)
    raw = min(candidate_paths(cards, C if requested == C else L, exact=exact), key=len)
    if requested == R:
        raw = [(j ^ 2, x) for j, x in raw]
    out = [Move(NAMES[EDGES[j][0]], NAMES[EDGES[j][1]], x) for j, x in raw]
    verify(cards, out, start=start)
    return out


def candidate_paths(cards, pile, *, exact=False):
    """Every plan generated for `cards` on `pile` (C or L), as (edge code, card) lists.

    The shortest one is the default plan. Each is within bounds(len(cards)).
    """
    active = _active(cards)
    m = len(active)
    target = tuple(range(1, m + 1))
    if pile == C:
        raw = _easy(active)
        optimal = raw is not None
    else:
        forward = _side_pass(active, target)
        backward = _side_pass(target, active)
        side_plans = [p for p in (forward, _reverse(backward) if backward is not None else None)
                      if p is not None]
        raw = min(side_plans, key=len, default=None)
        optimal = raw is not None and len(raw) == movement_lower_bound(cards, start=NAMES[pile])
    if optimal:
        return [raw]
    if exact or m < len(LEAVES):
        return [_exact_block(active, target, pile, pile)]
    # A center-start recursion also contains transfers between the two
    # outer piles. Try splitting off the first merge card at those nodes
    # as well as the original construction, in both planning directions.
    full_goal = tuple(range(1, len(cards) + 1))
    candidates = [] if raw is None else [raw]
    for mean_first, use_outer_split in product((False, True), repeat=2):
        forward = construct(cards, full_goal, pile, pile, mean_first, use_outer_split)
        inverse = _reverse(construct(target, active, pile, pile, mean_first, use_outer_split))
        candidates.extend((shorten(forward, m), shorten(inverse, m)))
        if m != len(cards):
            reduced = construct(active, target, pile, pile, mean_first, use_outer_split)
            candidates.append(shorten(reduced, m))
    return candidates
