"""Time-bounded beam-search improvements with a verified incumbent.

Search moves are adjacent top-card transfers. A timeout always returns a legal
plan no longer than the supplied fallback. Optimality applies to these search
endpoints, not to camera/dealing moves that have already happened.
"""

from collections import deque
from dataclasses import dataclass
from functools import lru_cache
import heapq
import math
import time

from exact_stack_planner import EDGES, Move, NAMES, _stacks, apply_moves


class _Timeout(Exception):
    pass


@dataclass(frozen=True)
class OptimizationResult:
    moves: tuple[Move, ...]
    fallback_moves: int
    lower_bound: int
    optimal: bool
    timed_out: bool
    nodes: int
    local_improvements: int
    elapsed_seconds: float
    memory_limited: bool = False
    beam_width: int | None = None

    def summary(self):
        return {"enabled": True,
                "algorithm": "Beam search with pattern databases and plan shortcuts",
                "scope": "remaining transfers after scanning and distribution",
                "fallback_moves": self.fallback_moves, "result_moves": len(self.moves),
                "saved_moves": self.fallback_moves - len(self.moves),
                "lower_bound": self.lower_bound, "optimal": self.optimal,
                "timed_out": self.timed_out, "nodes": self.nodes,
                "local_improvements": self.local_improvements,
                "memory_limited": self.memory_limited,
                "beam_width": self.beam_width,
                "status": "proven_optimal" if self.optimal else "improved" if len(self.moves) < self.fallback_moves else "no_improvement",
                "elapsed_seconds": round(self.elapsed_seconds, 4)}


def _neighbors(state):
    for source, destination in EDGES:
        if state[source]:
            stacks = list(state)
            card = stacks[source][0]
            stacks[source] = stacks[source][1:]
            stacks[destination] = (card,) + stacks[destination]
            yield tuple(stacks), Move(card, NAMES[source], NAMES[destination])


@lru_cache(maxsize=32)
def _pattern_table(goal):
    """Exact abstract distances; at most five tracked cards (2,520 states)."""
    distances = {goal: 0}
    queue = deque([goal])
    while queue:
        state = queue.popleft()
        stacks = state.split(b"\0")
        for source, destination in EDGES:
            if not stacks[source]:
                continue
            following = stacks.copy()
            following[source] = stacks[source][1:]
            following[destination] = stacks[source][:1] + stacks[destination]
            encoded = b"\0".join(following)
            if encoded not in distances:
                distances[encoded] = distances[state] + 1
                queue.append(encoded)
    return distances


class LowerBound:
    """Admissible maximum of displacement/stack access and additive PDB bounds."""

    def __init__(self, target, deadline=math.inf):
        self.target = _stacks(target)
        cards = [card for stack in self.target for card in stack]
        self.locations = {card: i for i, stack in enumerate(self.target) for card in stack}
        self.groups = [cards[i:i + 5] for i in range(0, len(cards), 5)]
        self.pattern_ids = {card: (i, j + 1) for i, group in enumerate(self.groups)
                            for j, card in enumerate(group)}
        self.tables = []
        for group in self.groups:
            if time.monotonic() >= deadline:
                raise _Timeout
            ids = {card: i + 1 for i, card in enumerate(group)}
            goal = b"\0".join(bytes(ids[card] for card in stack if card in ids) for stack in self.target)
            self.tables.append(_pattern_table(goal))

    def __call__(self, state):
        physical = 0
        projections = [[bytearray(), bytearray(), bytearray()] for _ in self.groups]
        for position, stack in enumerate(state):
            goal = self.target[position]
            settled = 0
            for actual, desired in zip(reversed(stack), reversed(goal)):
                if actual != desired:
                    break
                settled += 1
            for depth, card in enumerate(stack):
                destination = self.locations[card]
                physical += abs(position - destination)
                # A card in its goal compartment above an unsettled bottom
                # must leave and return before cards below it can be corrected.
                if position == destination and depth < len(stack) - settled:
                    physical += 2
                group, identity = self.pattern_ids[card]
                projections[group][position].append(identity)
        # Each real move changes exactly one disjoint pattern, so summing
        # abstract move costs is admissible; do not add this to physical.
        patterns = sum(table[b"\0".join(projected)]
                       for table, projected in zip(self.tables, projections))
        return max(physical, patterns)


def _incumbent_suffixes(initial, moves):
    """Known waypoints let a partial search reconnect to a valid plan early."""
    suffixes = {initial: 0}
    state = initial
    for index, move in enumerate(moves, 1):
        state = apply_moves(state, [move])
        suffixes[state] = index
    return suffixes


class _Beam:
    """Fixed-width beam search that keeps valid improvements on resource limits.

    Beam pruning never proves optimality. Only a matching admissible lower
    bound does.
    """

    local_seconds = 0.075
    max_active = 12

    def __init__(self, width=64, max_states=25000):
        self.width = width
        self.max_states = max_states
        self.nodes = 0
        self.timed_out = False
        self.memory_limited = False

    def search(self, initial, target, incumbent, deadline):
        heuristic = LowerBound(target, deadline)
        lower = heuristic(initial)
        best = tuple(incumbent)
        if lower == len(best):
            return best, True, lower
        suffixes = _incumbent_suffixes(initial, incumbent)

        def reconnect(state, path):
            nonlocal best
            if state in suffixes:
                suffix = incumbent[suffixes[state]:]
                if len(path) + len(suffix) < len(best):
                    best = path + tuple(suffix)

        frontier = [(initial, ())]
        seen = {initial: 0}
        while frontier:
            candidates = {}
            for state, path in frontier:
                if time.monotonic() >= deadline:
                    self.timed_out = True
                    return best, len(best) == lower, lower
                self.nodes += 1
                for following, move in _neighbors(state):
                    cost = len(path) + 1
                    if seen.get(following, math.inf) <= cost:
                        continue
                    route = path + (move,)
                    reconnect(following, route)
                    if len(best) == lower:
                        return best, True, lower
                    estimate = heuristic(following)
                    if cost + estimate >= len(best):
                        continue
                    candidates.setdefault(following, (estimate, route))
            selected = heapq.nsmallest(self.width, candidates.items(),
                                      key=lambda entry: entry[1][0])
            frontier = [(state, route) for state, (_, route) in selected]
            if len(seen) + len(frontier) > self.max_states:
                # Beam search is already approximate; forgetting older
                # duplicate entries bounds memory without discarding best.
                self.memory_limited = True
                seen = {}
            for state, route in frontier:
                seen[state] = len(route)
        return best, len(best) == lower, lower


def _erase_cycles(initial, moves):
    states = [initial]
    positions = {initial: 0}
    result = []
    for move in moves:
        state = apply_moves(states[-1], [move])
        if state in positions:
            index = positions[state]
            for removed in states[index + 1:]:
                del positions[removed]
            del states[index + 1:]
            del result[index:]
        else:
            result.append(move)
            states.append(state)
            positions[state] = len(result)
    return tuple(result)


def _repair_windows(initial, moves, engine, deadline):
    """Search small active-card windows without changing their full-stack endpoints."""
    moves = list(moves)
    improvements = 0
    position = 0
    state = initial
    while position < len(moves):
        if time.monotonic() >= deadline:
            break
        active = set()
        end = position
        while end < min(len(moves), position + 48):
            if len(active | {moves[end].card}) > engine.max_active:
                break
            active.add(moves[end].card)
            end += 1
        window = tuple(moves[position:end])
        if len(window) >= 4:
            target = apply_moves(state, window)
            abstract_initial = tuple(tuple(card for card in stack if card in active) for stack in state)
            abstract_target = tuple(tuple(card for card in stack if card in active) for stack in target)
            # Untracked cards form protected bases in each compartment.
            protected = tuple(len(stack) - len(block) for stack, block in zip(state, abstract_initial))
            slice_deadline = min(deadline, time.monotonic() + engine.local_seconds)
            try:
                replacement, _, _ = engine.search(abstract_initial, abstract_target, window, slice_deadline)
            except _Timeout:
                replacement = window
            if len(replacement) < len(window):
                if apply_moves(state, replacement, protected=protected) != target:
                    raise RuntimeError("Local repair disturbed a protected card")
                moves[position:end] = replacement
                improvements += 1
        # Overlapping windows can improve transitions between recipe stages.
        step = min(3, len(moves) - position)
        state = apply_moves(state, moves[position:position + step])
        position += step
    return tuple(moves), improvements


def optimize_plan(initial, target, fallback, *, seconds=2.0):
    """Return the best verified plan within a search budget, retaining fallback.

    Local search repairs and reconnections give anytime improvements; global
    search then tries to improve the remaining plan. Time limits are checked
    between nodes; small database construction/validation may add brief overhead.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 <= seconds <= 30:
        raise ValueError("Search time must be between 0 and 30 seconds")
    initial, target = _stacks(initial), _stacks(target)
    if {card for stack in initial for card in stack} != {card for stack in target for card in stack}:
        raise ValueError("Initial and target cards must match")
    fallback = tuple(fallback)
    if apply_moves(initial, fallback) != target:
        raise ValueError("Fallback does not reach target")
    started = time.monotonic()
    deadline = started + seconds
    best = _erase_cycles(initial, fallback)
    engine = _Beam()
    optimal = initial == target
    timed_out = False
    lower_bound = 0
    improvements = 0
    try:
        if not optimal:
            heuristic = LowerBound(target, deadline)
            lower_bound = heuristic(initial)
            if lower_bound == len(best):
                optimal = True
            else:
                best, improvements = _repair_windows(initial, best, engine, started + seconds * 0.55)
                engine.timed_out = False
                best, optimal, lower_bound = engine.search(initial, target, best, deadline)
                timed_out = getattr(engine, "timed_out", False)
                # A narrow beam can run out of candidates after pruning a
                # useful branch. Spend remaining time on wider restarts.
                while not optimal and not timed_out and engine.width < 512 and time.monotonic() < deadline:
                    engine.width *= 2
                    best, optimal, lower_bound = engine.search(initial, target, best, deadline)
                    timed_out = engine.timed_out
    except _Timeout:
        timed_out = True
    if apply_moves(initial, best) != target or len(best) > len(fallback):
        raise RuntimeError("Optimizer produced an invalid or longer plan")
    return OptimizationResult(best, len(fallback), lower_bound, optimal, timed_out,
                              engine.nodes, improvements, time.monotonic() - started,
                              engine.memory_limited, engine.width)
