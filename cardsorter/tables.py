"""Exact distance tables for small blocks (vectorised breadth-first search, numpy).

For every k <= K, ExactTables(K, goal) holds the exact number of adjacent moves from every
configuration of k cards to "k cards sorted on `goal`" (k!(k+1)(k+2)/2 states). A configuration
packs three top-first stacks into one int64 (4 bits per card). Goal R is served by mirroring
the goal-L table. load_tables() returns the tables for goals C and L, cached on disk.
"""

import itertools
import os
import sys
import time

import numpy as np

from .model import STACKS

K = 9  # largest block solved from the tables
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.table_cache')

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
        segs = top_segments(st, block)
        assert sum(len(x) for x in segs.values()) == len(block), 'block cards must occupy top segments'
        rank = {v: i for i, v in enumerate(sorted(block))}
        moves = self.walk(segs, rank)
        for s, d in moves:
            st[d].append(st[s].pop())
        return moves


def top_segments(conf, S):
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


def load_tables(k=K, cache_dir=CACHE_DIR):
    """{'C': ExactTables, 'L': ExactTables}. Built once (about a minute), then loaded from disk."""
    return {g: ExactTables(k, goal=g, cache_dir=cache_dir) for g in ('C', 'L')}
