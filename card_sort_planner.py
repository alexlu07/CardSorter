"""The partition-and-merge recipe in README.md, with counted adjacent moves."""

from dataclasses import dataclass
from functools import lru_cache

from exact_stack_planner import Move, NAMES, apply_moves, plan_block


@dataclass(frozen=True)
class SortPlan:
    moves: tuple[Move, ...]
    # End offsets in moves, excluding the 52 initial distribution moves.
    stages: tuple[tuple[str, int], ...]


class _Builder:
    def __init__(self, left, right, center=()):
        self.stacks = (tuple(left), tuple(center), tuple(right))
        self.moves = []
        self.stages = []

    def transfer(self, source, destination):
        """Route an outer-to-outer transfer through center, counting both legs."""
        if abs(source - destination) == 2:
            self.transfer(source, 1)
            self.transfer(1, destination)
            return
        move = Move(self.stacks[source][0], NAMES[source], NAMES[destination])
        self.stacks = apply_moves(self.stacks, [move])
        self.moves.append(move)

    def small(self, source, destination, count, budget):
        cards = self.stacks[source][:count]
        if len(cards) != count:
            raise ValueError("Active block is shorter than expected")
        protected = [len(s) for s in self.stacks]
        protected[source] -= count
        moves = plan_block(cards, source=NAMES[source], destination=NAMES[destination],
                           order=sorted(cards, reverse=True))
        if len(moves) > budget:
            raise RuntimeError(f"Small-block budget exceeded: {len(moves)} > {budget}")
        self.stacks = apply_moves(self.stacks, moves, protected=protected)
        self.moves.extend(moves)

    def partition(self, source, count, smaller_count, smaller_destination, larger_destination):
        active = self.stacks[source][:count]
        smaller = set(sorted(active)[:smaller_count])
        for _ in range(count):
            destination = smaller_destination if self.stacks[source][0] in smaller else larger_destination
            self.transfer(source, destination)

    def inplace(self, source, count):
        opposite = 2 - source
        smaller_count = 7 if count == 12 else 8
        larger_count = count - smaller_count
        self.partition(source, count, smaller_count, 1, opposite)
        self.small(1, source, smaller_count, 23 if count == 12 else 28)
        self.small(opposite, source, larger_count, 16 if count == 12 else 28)

    def merge(self, left_count, right_count):
        remaining = {0: left_count, 2: right_count}
        while any(remaining.values()):
            source = max((i for i in (0, 2) if remaining[i]), key=lambda i: self.stacks[i][0])
            self.transfer(source, 1)
            remaining[source] -= 1

    def mark(self, name, start, budget):
        cost = len(self.moves) - start
        if cost > budget:
            raise RuntimeError(f"{name} exceeded budget: {cost} > {budget}")
        self.stages.append((name, len(self.moves)))


def _plan_ascending(left, right):
    """Plan stages 2 and 3 after the scanned, value-based initial distribution."""
    left, right = tuple(left), tuple(right)
    if (len(left) != 20 or set(left) != set(range(33, 53)) or
            len(right) != 32 or set(right) != set(range(1, 33))):
        raise ValueError("Expected 33–52 on left and 1–32 on right, center empty")
    b = _Builder(left, right)
    original_right = right
    b.small(0, 2, 8, 28)
    b.mark("2A: transfer top eight", 0, 28)
    start = len(b.moves)
    b.inplace(0, 12)
    b.mark("2B: sort twelve in place", start, 56)
    start = len(b.moves)
    b.merge(12, 8)
    b.mark("2C: merge bottom twenty", start, 20)
    if b.stacks != ((), tuple(range(33, 53)), original_right):
        raise RuntimeError("Stage 2 failed to preserve the waiting group")
    start = len(b.moves)
    b.partition(2, 16, 8, 0, 1)
    b.small(0, 0, 8, 30)
    b.small(1, 0, 8, 28)
    b.mark("3A: transfer top sixteen", start, 82)
    start = len(b.moves)
    b.inplace(2, 16)
    b.mark("3B: sort sixteen in place", start, 80)
    start = len(b.moves)
    b.merge(16, 16)
    b.mark("3C: merge top thirty-two", start, 32)
    if b.stacks != ((), tuple(range(1, 53)), ()):
        raise RuntimeError("Plan did not finish with the sorted deck in center")
    if len(b.moves) + 52 > 350:
        raise RuntimeError("Full plan exceeds 350 movements")
    return SortPlan(tuple(b.moves), tuple(b.stages))


def plan_remaining(left, right, *, descending=False):
    """Plan a center result; optionally reverse values for a final side transfer.

    Ascending expects 33–52 left and 1–32 right. Descending expects 1–20 left
    and 21–52 right. Actual card IDs remain unchanged in returned moves.
    """
    if not descending:
        return _plan_ascending(left, right)
    plan = _plan_ascending([53 - value for value in left], [53 - value for value in right])
    return SortPlan(tuple(Move(53 - move.card, move.source, move.destination) for move in plan.moves),
                    plan.stages)


# Exhaustive small-block maxima for side-in-place, center-to-side, and
# side-to-opposite-side. Reflections/relabelings preserve all distances.
_SIDE_BASE = {
    1: (0, 1, 2), 2: (6, 4, 4), 3: (10, 7, 8), 4: (14, 12, 12),
    5: (18, 15, 16), 6: (22, 20, 20), 7: (26, 23, 24), 8: (30, 28, 28),
}


@lru_cache(maxsize=None)
def side_strategy(kind, count):
    """Minimum worst-case bound over this recursive partition family, not all plans.

    A prefix is the group destined for the TOP of the final block; a suffix
    goes below it. Both groups are nonempty, so all recursive calls shrink.
    Returns (movement bound, prefix size); at most eight cards use exact search.
    """
    kinds = ("in_place", "center_to_side", "side_to_side")
    if kind not in kinds or type(count) is not int or not 1 <= count <= 52:
        raise ValueError("Invalid side strategy request")
    if count <= 8:
        return _SIDE_BASE[count][kinds.index(kind)], 0
    candidates = []
    for prefix in range(1, count):
        suffix = count - prefix
        if kind == "in_place":
            # Prefix crosses to the opposite side; suffix waits in center.
            cost = count + prefix + side_strategy("center_to_side", suffix)[0] + side_strategy("side_to_side", prefix)[0]
        elif kind == "center_to_side":
            # Suffix goes directly to destination; prefix to the opposite side.
            cost = count + side_strategy("in_place", suffix)[0] + side_strategy("side_to_side", prefix)[0]
        else:
            # Suffix crosses to destination; prefix waits in center.
            cost = 2 * count - prefix + side_strategy("in_place", suffix)[0] + side_strategy("center_to_side", prefix)[0]
        candidates.append((cost, prefix))
    return min(candidates)


def side_prefix_size():
    return side_strategy("in_place", 52)[1]


def side_movement_budget():
    return side_strategy("in_place", 52)[0]


def _sort_to_side(builder, source, destination, count, order):
    """Recursively sort only an active top block, preserving all other cards."""
    order = tuple(order)
    before = builder.stacks
    active = before[source][:count]
    if len(active) != count or set(active) != set(order) or len(order) != count:
        raise ValueError("Active cards and desired block order must match")
    expected = [list(stack) for stack in before]
    del expected[source][:count]
    expected[destination][:0] = order
    start = len(builder.moves)
    kind = "in_place" if source == destination else "center_to_side" if source == 1 else "side_to_side"
    budget, prefix_size = side_strategy(kind, count)
    if count <= 8:
        protected = [len(stack) for stack in before]
        protected[source] -= count
        moves = plan_block(active, source=NAMES[source], destination=NAMES[destination], order=order)
        builder.stacks = apply_moves(before, moves, protected=protected)
        builder.moves.extend(moves)
    else:
        prefix, suffix = order[:prefix_size], order[prefix_size:]
        prefix_cards = set(prefix)
        if kind == "in_place":
            prefix_destination, suffix_destination = 2 - source, 1
        elif kind == "center_to_side":
            prefix_destination, suffix_destination = 2 - destination, destination
        else:
            prefix_destination, suffix_destination = 1, destination
        for _ in range(count):
            target = prefix_destination if builder.stacks[source][0] in prefix_cards else suffix_destination
            builder.transfer(source, target)
        _sort_to_side(builder, suffix_destination, destination, len(suffix), suffix)
        _sort_to_side(builder, prefix_destination, destination, len(prefix), prefix)
    if builder.stacks != tuple(tuple(stack) for stack in expected):
        raise RuntimeError("Side recursion disturbed a protected block or sorted incorrectly")
    if len(builder.moves) - start > budget:
        raise RuntimeError("Side recursion exceeded its movement bound")


def plan_side_remaining(center, opposite, *, start="left"):
    """Sort directly back to a side after camera feed/value partitioning.

    The smallest prefix_size IDs wait on the opposite side, all others in
    center, with the starting side empty. No whole-deck center staging or
    sorted center-to-side return is part of this strategy.
    """
    if start not in ("left", "right"):
        raise ValueError("A direct side plan requires left or right")
    prefix_size = side_prefix_size()
    center, opposite = tuple(center), tuple(opposite)
    if (len(center) != 52 - prefix_size or set(center) != set(range(prefix_size + 1, 53)) or
            len(opposite) != prefix_size or set(opposite) != set(range(1, prefix_size + 1))):
        raise ValueError("Unexpected direct-side camera partition")
    destination = NAMES.index(start)
    other = 2 - destination
    builder = _Builder(() if destination == 0 else opposite,
                       () if destination == 2 else opposite, center=center)
    _sort_to_side(builder, 1, destination, 52 - prefix_size, tuple(range(prefix_size + 1, 53)))
    builder.stages.append((f"2: sort cards {prefix_size + 1}–52 directly onto {start}", len(builder.moves)))
    _sort_to_side(builder, other, destination, prefix_size, tuple(range(1, prefix_size + 1)))
    builder.stages.append((f"3: sort cards 1–{prefix_size} directly onto {start}", len(builder.moves)))
    if 52 + prefix_size + len(builder.moves) > side_movement_budget():
        raise RuntimeError("Direct side plan exceeded its movement bound")
    return SortPlan(tuple(builder.moves), tuple(builder.stages))
