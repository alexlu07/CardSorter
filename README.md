# Three-compartment card sorter

Given the top-to-bottom order of a scanned deck, the planner sorts cards 1–52 back into their starting compartment. Each transfer moves one exposed card between adjacent compartments. Counts begin with the deck order known.

| Start | Prepare original top group | Prepare remainder | Merge 52 down to 1 | Guaranteed total |
|---|---|---|---|---|
| Center | 22 onto left, ≤106 | 30 onto right, ≤164 | 52 | **322** |
| Left | 31 onto center, ≤171 | 21 onto right, ≤106 | 73 | **350** |

Both temporary piles have the largest card on top. For the left start, each right-pile card crosses center on its way home. Right starts mirror left starts. These fixed plans (Strategy A, [card_sorter.py](card_sorter.py)) give the certified bounds. Blocks of up to 11 cards use exact search; larger blocks use recursive splits and merges.

## Combined planner

[combined_sorter.py](combined_sorter.py) keeps every certified Strategy A plan as a candidate and adds per-deck candidates, so no deck can exceed 322 (center) or 350 (side). For each deck it:

1. Generates every Strategy A variant (worst-case-first or mean-first, with or without the one-card-across split, forward and time-reversed, with and without the settled bottom run).
2. Runs Strategy B's per-deck hub-distribution DP ([hubsort.py](hubsort.py)) on the deck and on its inverse. The inverse plan is played time-reversed.
3. Runs a per-deck DP over Strategy A's merge family (`MergeDP`), on the deck and on its inverse. It picks the split point, the pile assignment and the one-card-across option for every block. It uses exact 9-card table leaves and credits the guaranteed merge cancellation.
4. Polishes every candidate, forwards and time-reversed. Polishing deletes pointless excursions and replaces any window that moves at most 9 cards, and starts or ends with exactly those cards on top of any stack, by its exact optimum. The three best candidates also get windows of 10–11 cards repaired by A* search.
5. Returns the shortest candidate after an independent replay with `card_sorter.verify`. It asserts the 322 / 350 bound.

| 512 seeded shuffles, mean (max) | Center | Side |
|---|---:|---:|
| Strategy A | 266.13 (288) | 295.88 (312) |
| Strategy B, polished (as reported) | 275.07 (290) | 289.34 (308) |
| Shorter of A and B per deck | 265.72 | 288.38 |
| **Combined planner** | **260.13 (276)** | **279.42 (296)** |
| Seed 42 | 260 | 272 |

```python
from combined_sorter import plan

moves = plan(deck, start="C")  # L, C, or R; card_sorter.Move(source, destination, card)
```

The first call builds the exact 9-card tables for goals C and L. This takes about a minute and needs about 1 GB of RAM. The tables are cached in `.table_cache/`, so later runs load them in seconds. The planner needs numpy and takes about 2–3 seconds per deck. `sorter.py` (the hardware path used by `cards.py` and the visualizer) now plans with the combined planner.

```sh
python combined_sorter.py --seed 42 --start L
python combined_sorter.py --benchmark 512 --start C --jobs 8
```

## Strategy A on its own

| Measurement | Center | Left |
|---|---:|---:|
| Worst-case optimum interval | 204–322 | 206–350 |
| Reverse deck optimum | 204 | 206 |
| Uniform-shuffle mean ceiling | <276.065 | <307.750 |
| Reported mean over 512 seeded shuffles | 266.13 | 295.88 |
| Largest in that sample | 288 | 312 |
| Seed 42 | 264 | 294 |

```python
from card_sorter import plan

moves = plan(deck, start="C")  # L, C, or R
```

Pass `exact=True` to search for a shortest route for a specific deck. A full-deck search can exhaust time or memory.

```sh
python cards.py --demo --seed 42 --start center --show-moves
python visualizer.py
python card_sorter.py --start L --bounds 52
```

Open the visualizer at http://127.0.0.1:8765 to replay a seeded or custom deck. The optional time-limited optimizer can try to shorten the verified plan. [Seed 42 transfers](example_moves_seed42.txt) lists both routes. [The C++ certifier](certify_blocks.cpp) reproduces the small-block constants used by the bound calculation.

## Hardware with an unknown deck order

Pass the known order to `CardSorter.run(deck=deck)` for the strategy above. Calling `run()` with no deck retains the camera-driven strategy documented below, including its scanning transfers and separate budgets.

## Initial scan and distribution

The default demo scans and distributes, plans all remaining transfers, then
executes them in simulation. It prints movement counts for each stage and the
final stacks. The selected starting compartment finishes 1–52 from top to bottom.
Every outer-to-outer transfer counts as two adjacent movements.

Load exactly 52 standard cards in the selected compartment, with both others
empty. Card faces must be visible to the middle camera. For a middle start,
stage 1 works as follows:

1. Capture and recognize the stationary top card.
2. Validate its identity and reject duplicates.
3. Transfer exactly one card based on its ID: 33–52 to the left,
   1–32 to the right. Starting position does not determine the destination.
4. Confirm physical delivery before recording the move and scanning again.

IDs use clubs 1–13, diamonds 14–26, hearts 27–39, spades 40–52, with
A, 2, …, 10, J, Q, K in each suit. Receiving cards land on top, so each
destination stack reverses its arrival order. State lists are top-to-bottom.
For a middle start, this leaves the final bottom twenty (7 of hearts through
king of spades) on the left and top thirty-two (ace of clubs through 6 of hearts)
on the right. A side start uses the direct partition described next instead.

## Direct side-start method

`SideDealer` repeats these operations for every card, without assuming its
identity before the camera reads it:

1. Feed one top card from the starting side into the middle; confirm delivery.
2. Scan the stationary middle top card and reject invalid/duplicate identities.
3. If it is 1–8, transfer it to the opposite side immediately. Otherwise leave
   it in the middle, beneath the next incoming card.

The starting side finishes empty, the middle holds 9–52, and the opposite side
holds 1–8. Scanning is integrated into the partition: **52 + 8 = 60 transfers**.
The system never first stages the entire deck in the middle.

Next, sort-transfer the 44 middle cards directly onto the starting side,
ascending top-to-bottom, while leaving the opposite eight protected. Finally,
sort-transfer the eight opposite cards above those 44, also ascending. The
finished 44-card base stays protected. Both other compartments finish empty.

The recursive planner uses the same exact small-block primitives as the middle
method. For a larger block, it partitions by the desired final order, sorts the
bottom group first, then layers the top group above it. It evaluates every
nonempty prefix/suffix split to minimize the compositional movement bound.

Let `I(n)` be the bound for sorting in place on a side, `C(n)` for sorting from
the middle to a side, and `O(n)` for sorting between opposite sides. For a final
top prefix of `a` cards and bottom suffix of `b = n - a`:

| Operation | Bound minimized over every split |
| --- | --- |
| Side in place | `n + a + C(b) + O(a)` |
| Middle to side | `n + I(b) + O(a)` |
| Opposite side to side | `2n - a + I(b) + C(a)` |

For at most eight cards, bounds come from exhaustive exact distances and plans
use exact search. For 52 cards, the recurrence chooses `a = 8`, `b = 44`, giving
**60 + C(44) + O(8) = 60 + 290 + 28 = 378**. This is the best bound in this
partition family, not a proof of the globally shortest strategy. Optional heuristic
search can further improve the actual remaining plan after scanning.

Each recursive call verifies the result, its budget, and that all cards below
the active blocks are unchanged. Left and right starts use reflected versions
of the same strategy; both have the same bounds and unoptimized movement counts
for the same input order.

## Middle-start method

The stages below apply when the deck starts and finishes in the middle.

The method combines partitioning, exact planning for small groups, and merging
directly into the final center stack. This avoids repeatedly returning a whole
mixed group to the center. Scanning takes place during stage 1 and does not add
card movements. One movement means transferring one top card to an adjacent
compartment. A left-to-right or right-to-left transfer requires two movements
through the center.

### Stage 1: Distribute by value — 52 movements

Use `InitialDealer` to scan and distribute all cards as described above:
33–52 left, 1–32 right. The center finishes empty. Each receiving stack reverses
its cards' arrival order; the controller records that actual order for planning.

### Stage 2: Sort the bottom twenty into the center — at most 104 movements

1. Take the current top eight left cards, regardless of value. Sort-transfer
   them onto the right, largest on top, above the waiting 32-card group.
   Use the exact small-group planner: at most **28 movements**.
2. Sort the remaining twelve left cards in place, largest on top, using the
   seven/five procedure below: at most **56 movements**.
3. Merge the twelve left cards and eight active right cards into the center.
   Repeatedly transfer the larger available top card. Stop after these twenty
   cards; leave the waiting 32 right cards untouched: exactly **20 movements**.

The largest card goes into the center first and therefore ends at the bottom.
The center now reads **33–52 top-to-bottom**. Stage cost: **28 + 56 + 20 = 104**.

### Stage 3: Sort the top thirty-two onto the center — at most 194 movements

Keep the completed center twenty protected throughout this stage. Temporary
cards may be placed above them, but those twenty may never be removed.

1. Take the current top sixteen right cards, regardless of value. Sort-transfer
   them onto the left, largest on top, using the eight/eight transfer procedure
   below: at most **82 movements**.
2. Sort the remaining sixteen right cards in place, largest on top, using the
   eight/eight in-place procedure below: at most **80 movements**.
3. Merge the two descending sixteen-card groups onto the center by repeatedly
   transferring the larger available top card: exactly **32 movements**.

Card 32 lands directly above 33, and card 1 lands last. The center finishes
**1–52 top-to-bottom**, with both sides empty. No additional final transfer is
needed. Stage cost: **82 + 80 + 32 = 194**.

### Sort twelve cards in place in a side compartment

Partition by value within the active twelve, processing them in their current
top-to-bottom order. Keep any cards beneath active blocks protected.

1. Send the seven smaller cards to the center and the five larger cards to the
   opposite side, via the center. Distribution costs **7 + 2 × 5 = 17** movements.
2. Sort-transfer the seven center cards back to the original side, largest on
   top: at most **23** movements.
3. Sort-transfer the five opposite-side cards back above those seven, largest
   on top: at most **16** movements.

The larger five sit above the smaller seven, so all twelve are descending.
Total: **17 + 23 + 16 = 56** movements.

### Sort sixteen cards while transferring between side compartments

1. Send the eight smaller cards to the destination side, via the center, and
   the eight larger cards to the center. Distribution costs **2 × 8 + 8 = 24**
   movements. Each two-leg crossing is completed before processing another card.
2. Sort the destination's eight cards in place, largest on top: at most **30**
   movements.
3. Sort-transfer the eight center cards onto them, largest on top: at most **28**
   movements.

Total: **24 + 30 + 28 = 82** movements.

### Sort sixteen cards in place in a side compartment

1. Send the eight smaller cards to the center and the eight larger cards to the
   opposite side, via the center. Distribution costs **8 + 2 × 8 = 24** movements.
2. Sort-transfer the center eight back to the original side, largest on top:
   at most **28** movements.
3. Sort-transfer the opposite-side eight back above them, largest on top:
   at most **28** movements.

Total: **24 + 28 + 28 = 80** movements.

### Exact planning and protected cards

Every small group has at most eight active cards. Its shortest transfer sequence
comes from bidirectional breadth-first search. Cards below the active blocks are
protected, and merging stops at the boundaries of the active groups. Later moves
use the identities recorded during the initial scan and confirmed transfers;
they do not require additional camera scans.

The planner represents the active cards in all three compartments, generates
legal adjacent top-card transfers, and searches forward from the initial state
and backward from the target. Each movement has equal cost; expanding breadth-first
layers finds a shortest sequence. Only small groups require exact search; the
larger deck follows the fixed partition-and-merge recipe above.

Exclude protected cards from the search. During replay, specify the number of
protected bottom cards in each compartment. Temporary cards can be placed above
these boundaries without disturbing the waiting groups.

### Movement budget

| Stage | Maximum movements |
| --- | ---: |
| Initial distribution | 52 |
| Sort and merge bottom twenty | 104 |
| Sort and merge top thirty-two | 194 |
| Total for a middle start | 350 |
| Direct side scan and partition | 60 |
| Direct middle-to-start transfer-sort of 44 cards | 290 |
| Direct opposite-to-start transfer-sort of eight cards | 28 |
| Total for a side start | 378 |

Previously verified maximum distances to a target side stack from a single starting
stack on the left/center/right are 18/15/16 for five cards, 26/23/24 for seven,
and 30/28/28 for eight. Reflection and relabeling cover the other side and any
desired order. These bounds give the stated 350 maximum for this recipe; the
whole-deck plan is not claimed to be globally shortest. Every generated plan
also checks its stage budgets and final result before physical sorting begins.
A particular starting deck can require fewer movements. The seed-42 middle
demo uses 318; the default left demo uses 338.

### Batch simulation results

A full run in **middle-start mode** over **10,000 shuffled decks**, using seeds 0–9999, completed with
**zero failures**. Every deck finished 1–52 in the center with empty side stacks.
Counts include the initial 52 distribution transfers:

| Measure | Movements |
| --- | ---: |
| Minimum | 278 |
| Average | 306.3986 |
| Maximum | 328 |
| Runs reaching 350 | 0 |

The run independently replayed every actual simulated hardware event, checking
adjacent top-card transfers, card conservation, scan order, the initial value
partition, protected waiting/finished groups, stage budgets, and movement counts.
All 10,000 samples were strictly below 350; this batch exercises simulated
hardware and does not validate physical motors, cameras, or sensors.
Detailed statistics and the movement histogram are in
[`simulation-results.json`](simulation-results.json). Reproduce the highest-count
sample with `python3 cards.py --demo --start center --seed 3477`. These statistics
describe middle-start mode; they do not describe the direct side-start method.

The direct side strategy passed **302 cases per side**: seeds 0–299 plus ordered
and reversed decks. Each side used 278–354 moves, averaging about 337.41, and
both produced identical counts on reflected inputs. A further 102 middle cases
passed, as did 12 optimized cases across all start positions. Every simulated
transfer was independently replayed to check legal top-card movement, conservation,
camera scan order, the direct partition, and protected groups. Feed, recognition,
and opposite-side routing failures stopped with only confirmed progress recorded.
Detailed counts are in [`direct-side-results.json`](direct-side-results.json).
The 378 bound is a worst-case guarantee for the direct strategy; some sampled
side decks exceeded 350, so the middle method's 350 guarantee must not be applied
to side starts.

## Files and planner API

- `cards.py`: card numbering, `InitialDealer` for middle starts, `SideDealer` for
  direct side starts, simulated hardware, and CLI.
- `exact_stack_planner.py`: `Move`, `exact_plan`, `plan_block`, `apply_moves`.
- `card_sort_planner.py`: `plan_remaining(left, right)` returns all remaining
  middle-start moves; `side_strategy` selects recursive splits and
  `plan_side_remaining` plans direct side sorting after its camera partition.
- `sorter.py`: `CardSorter` executes initial dealing and the remaining plan.
- `heuristic_planner.py`: time-bounded `optimize_plan`, admissible lower bounds,
  pattern databases, local repairs, beam search, and A*.
- `visualizer.py`, `visualizer.html`: local simulation server and interactive
  playback of the three compartments, scans, and card movements.
- `simulation-results.json`: results of the 10,000-deck simulation batch.
- `direct-side-results.json`: separate direct-side and middle-regression results.
- `search-benchmark.json`: the 207-run paired comparison and solver-retention decision.

`Move(card, source, destination)` describes a single adjacent top-card transfer;
it does not operate a motor. `exact_plan(initial, target)` finds a shortest
sequence between arbitrary arrangements of at most eight active cards total.
`plan_block(cards, source=..., destination=..., order=...)` wraps that search for
a group starting together in one compartment. `apply_moves(stacks, moves,
protected=...)` replays moves and returns the resulting stacks, rejecting
nonadjacent transfers, incorrect top cards, or removal of protected cards.

`plan_remaining(left, right)` expects the scanned 33–52 left group and 1–32 right
group, with an empty center. It returns a `SortPlan` containing the moves for
stages 2 and 3 and their end offsets. Its optional `descending=True` remains a
standalone utility; the controller no longer uses reversed IDs or a final
whole-deck return for side starts. `plan_side_remaining(center, opposite,
start="left")` expects 9–52 in the middle and 1–8 on the opposite side.
`CardSorter(hardware, start="left").run()` chooses the appropriate dealer and
planner, optionally improves the remaining plan, then executes it.
Construct simulated hardware with the same start value, for example
`SimulatedHardware(deck, start="right")` and `CardSorter(hardware, start="right")`.
For optional improvement, use `CardSorter(hardware, start="right", optimize=True,
search_seconds=2, search_algorithm="beam")`. `state.optimization` contains the search statistics; the
standalone optimizer returns an `OptimizationResult` with moves and a
serializable `.summary()`.

For example, plan an active group while leaving cards below it untouched:

```python
from exact_stack_planner import plan_block, apply_moves

cards = [3, 1, 4, 2]
moves = plan_block(cards, source="left", destination="center", order=[1, 2, 3, 4])
final = apply_moves((cards + ["left_base"], ["center_base"], ["right_base"]),
                    moves, protected=(1, 1, 1))
assert final == (("left_base",), (1, 2, 3, 4, "center_base"), ("right_base",))
```

Lists are top-to-bottom; compartment names are `left`, `center`, `right`.
Planner card IDs must be distinct and hashable; they can be numbers or strings.
The complete-deck recipe specifically uses integer IDs 1–52.

The four-card example above has a minimum cost of eight movements. To sort in
place, use the same source and destination:

```python
moves = plan_block([3, 1, 4, 2], source="center", destination="center",
                   order=[1, 2, 3, 4])
```

For the descending groups required before merging:

```python
top_eight = [42, 35, 49, 39, 51, 44, 33, 47]
moves = plan_block(top_eight, source="left", destination="right",
                   order=sorted(top_eight, reverse=True))
```

For arbitrary distributed arrangements:

```python
from exact_stack_planner import exact_plan

initial = ([3, 1], [4], [2])
target = ((1, 4), (2,), (3,))
moves = exact_plan(initial, target)
assert len(moves) == 10
assert apply_moves(initial, moves) == target
```

## Connecting hardware

The current executable simulates both scanning and motors. It does not recognize
camera images or drive real hardware. Implement `SortingHardware` in `sorter.py`,
which extends the initial `Hardware` protocol, then run:

```python
from sorter import CardSorter

sorter = CardSorter(adapter, start="left")  # Load the deck on the left.
state = sorter.run()
```

- `scan_top()` must acquire a fresh image and return a recognized ID, raising
  on ambiguous or unreadable cards. Keep the card stationary during capture.
- `transfer_one(side)` must singulate a card, drive the appropriate adjacent
  roller path, confirm arrival using sensors, and stop before returning. It must
  enforce a bounded timeout and detect jams/double feeds. Encoder movement alone
  does not prove that a card moved.
- `move_one(source, destination)` must support all four adjacent directions,
  with the same single-card, sensor-confirmation, stop, and timeout requirements.
  Both arguments are compartment names. No direct left/right jump is requested.
- `stop()` must disable every roller and remain usable after a fault. Physical
  motor control should also have a watchdog independent of this Python process.

The mechanism needs a separator/retard pad to prevent double feeds, a way to keep
the changing stack height within roller reach, and an unobstructed view of the
card index. A camera cannot identify a face-down card from its back.

On any scan, planning, or transfer error, the controller requests a motor stop and
raises the error. `sorter.state` retains the phase, confirmed movement count,
initial-deal state, planned moves, and any pending sorting move. After distribution,
`state.stacks` contains the last confirmed full arrangement. During distribution,
unscanned identities are unknown and `state.stacks` is `None`; consult
`state.initial_deal` for known partial stacks and its pending source,
destination, and card. `source_remaining` counts source cards not yet fed;
`confirmed_moves` counts only confirmed initial transfers. On an uncertain
side-to-camera feed, the pending card is unknown. If the feed succeeds but the
scan fails, `awaiting_scan` is true and the feed is counted. Every routing move
is separately confirmed. `dealing_stages` contains initial-stage movement
offsets; `sorting_moves_confirmed` counts subsequent planned transfers.

After a failed transfer, physical positions may differ from recorded positions;
inspect and reconcile them before restarting. There are no automatic retries.
A controller cannot be run twice. State is in memory; power-loss recovery is not
implemented. The movement guarantee assumes successful single-card transfers.

## Suggested prototype components

- Raspberry Pi for camera recognition and the Python controller.
- [Raspberry Pi Camera Module 3 Standard](https://www.raspberrypi.com/products/camera-module-3/):
  12 MP and autofocus; start with stop-and-scan capture and diffuse lighting.
  Mount to show the card corner across the full stack-height range.
- [Pololu 100:1 HPCB 12 V gearmotor with encoder](https://www.pololu.com/product/5216):
  a candidate for each independently driven roller path, rated 330 RPM no-load.
  Select final gearing after measuring feed torque and roller diameter.
- [Pololu DRV8876 carrier #4036](https://www.pololu.com/product/4036/specs):
  one per motor; supports bidirectional drive, 4.5–37 V, 1.3 A continuous.
  Use a separate appropriate motor supply, common logic ground, and current limiting.
- Card-passage sensors at the feed/delivery paths, plus a double-feed detection
  method; exact sensor choice depends on the mechanical layout.

For continuous-motion imaging, consider the
[Raspberry Pi Global Shutter Camera](https://www.raspberrypi.com/documentation/accessories/global-shutter-camera.html)
with an appropriate lens and strong lighting. It is unnecessary for the first
stationary-card prototype.
