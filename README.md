# Three-compartment card sorter

Automatic sorting of a standard 52-card deck using three side-by-side stacks,
adjacent motor-driven rollers, and a camera above the middle compartment.
The complete partition-and-merge method is implemented in Python 3.10+ with no
dependencies. The demo simulates the camera and motors.

```sh
python3 cards.py --demo
python3 cards.py --demo --seed 12 --show-moves
python3 cards.py --demo --start center
python3 cards.py --demo --start right
python3 cards.py --demo --optimize --search-seconds 2
python3 cards.py --demo --optimize --search-algorithm astar --search-seconds 2
```

`--start` selects both the starting and finishing compartment: `left` (default),
`center`, or `right`. The final deck is always 1–52 from top to bottom in that
same compartment, with both other compartments empty. The camera stays over the
middle compartment.

Side starts use a direct strategy: feed each card through the middle camera,
leave cards 9–52 in the middle, and send cards 1–8 to the opposite side. Sort
9–52 directly onto the starting side, then sort 1–8 above them. There is no
whole-deck loading pass or whole-deck final return. The maximum is **378 for
side starts**, or **350 for a middle start**. With seed 42, the default left
mode uses 338 moves; middle mode uses 318. A dynamic program selects the lowest
proven movement bound within the recursive partition strategy family; this is
not a claim that every full-deck plan is globally optimal.

## Visualizer

```sh
python3 visualizer.py
```

Open **http://127.0.0.1:8765** in a browser. The visualizer runs the same Python
sorter and replays its recorded camera scans and confirmed transfers. Use Play,
Pause, Back, Step, Restart, or Finish; drag the timeline or select a stage to jump
through the sequence. Select **Start & finish**, choose a shuffle seed or generate a new shuffle, and change
playback speed. The three compartments show their top cards, counts, and full
top-to-bottom card lists. Muted chips mark the waiting eight cards and completed
44-card base for side starts, or the waiting 32-card group and completed bottom
twenty for middle starts. Search can change these boundaries; shading is then
omitted.

The server is local to this computer and needs no packages or internet access.
Use `python3 visualizer.py --port 9000 --seed 123 --start right` to change its port,
initial shuffle, or starting/finishing compartment. The default is left. Stop it
with Ctrl+C. This only operates simulated hardware.

For a specific starting order, choose **Deck order → Custom shuffle**. Enter all
52 card IDs from **top to bottom**, separated by commas, spaces, or newlines,
then select **Load deck**. IDs must contain every integer 1–52 exactly once;
duplicates, missing cards, and invalid values are rejected. **Use current deck**
copies the currently loaded starting order, while **1–52** and **52–1** fill
ordered and reversed decks. Changing the starting compartment keeps your custom
order. **New shuffle** switches back to a generated shuffle.

## Optional search optimization

Enable **Improve plan** in the visualizer, or pass `--optimize` to the demo.
Select **Beam search** (default), **A***, or **IDA*** and set **Search seconds**
(0–30, default 2). Changing the algorithm while search is enabled reloads the
simulation. Use **Load deck** after changing the time budget. The page and CLI
report before/after remaining moves, saved moves, search time, and whether the
result is **best found** or **proven optimal after scanning**. An unsuccessful
search explicitly says **No improvement found · fallback retained**. Optimization
is off by default; without it, the partition-and-merge stages run as before.

| Algorithm | Purpose and limits |
| --- | --- |
| Beam search | Default for practical improvements. Keeps 64 candidates per depth, restarting with widths up to 512 if time remains. Pruning can miss shorter solutions, so it does not generally prove optimality. |
| A* | Expands the cheapest estimated complete paths first. Stops safely at the time budget or a 25,000 discovered-state/open-entry cap. Can prove optimality when every cheaper candidate is ruled out. |
| IDA* | Searches increasing cost thresholds with small path memory. Retained for comparison; repeated work can consume the budget without improving a full-deck plan. |

The controller first completes the required middle-camera scan and distribution;
side starts scan each newly fed card as part of their direct partition.
It then builds the existing bounded plan as a fallback and runs the optimizer
before executing any remaining moves. The optimizer removes cycles and repairs
overlapping sections of the plan using the selected algorithm. A*/beam repairs
can involve up to twelve active cards; IDA* repairs use at most eight. A* and
beam search can reconnect to later known states in the incumbent plan, so a
partial search can produce a complete improvement without reaching the final
goal by itself. Remaining time is used for global search between the scanned
arrangement and the chosen finishing compartment. Every candidate is independently
replayed before execution. A timeout or memory limit retains the best verified
plan, never a longer one.

The heuristic takes the maximum of two admissible lower bounds: compartment
travel plus unavoidable removal/return of cards above unsettled stack bases,
and additive exact pattern databases of at most five cards each. Each physical
move changes only one disjoint pattern, so summing pattern distances does not
overestimate. Tables are built by reverse breadth-first search and cached with
a bounded cache. The searches reject redundant revisits. IDA* uses path-cycle
detection; A* stores best discovered costs and a bounded priority queue. Beam
search keeps a fixed-width layer and bounds its duplicate table, forgetting old
entries if necessary without discarding its best valid plan.

Exhaustive A* search, exhaustive IDA* thresholds, or a matching admissible lower
bound can justify an optimality label. Beam search receives that label only if
the result matches the admissible lower bound. Small local optima do not prove the full remaining plan is
optimal. The label applies to **remaining moves from the scanned/distributed
state**, not to the whole process: initial feeding and scanning transfers have
already occurred and cannot be optimized away. The standalone
`optimize_plan(initial, target, fallback, seconds=..., algorithm="beam")` API can search between
other fully known arrangements, including a whole-deck initial state.

The budget covers search, with checks between nodes. Small database builds and
plan validation can add brief overhead. Full-deck optimal search is generally
intractable within this limit; finding improvements is the practical objective.
Saved-move counts may vary with the time budget and computer speed. Optimized
playback can combine the recipe's stages into one stage because the search can
cross their boundaries; the earlier waiting-group shading is then omitted.

For example, a custom 1–52 deck starting in the middle finishes in 104 total
moves with optimization: the fixed 52 scan/distribution transfers and a
52-transfer merge. That remaining merge is proven optimal. This does not mean
104 is globally optimal for a deck already sorted before scanning; the scan
and distribution stage is fixed in this controller.

Validation included admissibility checks against independent exact distances
for all 360 four-card and 20,160 six-card arrangements, shortest-plan comparisons,
and 24 time-limited full-deck runs across all three starting compartments.
Timeouts retained valid plans, and every full-deck result was no longer than
its fallback. The earlier 10,000-run statistics describe the unoptimized recipe.

### Three-solver benchmark

The expanded benchmark ran **207 solver trials on 69 paired cases**. The default
2-second tier used 20 shuffled decks (seeds 0–17, 42, 123) in all three starting
compartments, giving 60 cases per solver. A longer 5-second tier used three new
decks (seeds 101, 202, 303), again in all three compartments, giving nine cases
per solver. Within each tier all algorithms received identical decks, scanned
states, and fallbacks. Their order was rotated and the pattern cache was cleared
before each run. The source files stayed unchanged throughout the benchmark.

Average **total physical transfers**, including the shared camera/feed prefix:

| Algorithm | 2-second budget, 60 cases | 5-second budget, nine cases |
| --- | ---: | ---: |
| IDA* | 318.93 | 320.44 |
| A* | 311.47 | 313.33 |
| Beam search | 310.93 | 312.00 |

The columns use different deck sets; they compare algorithms within each budget,
not the effect of increasing time on the same decks. All 207 candidates passed
independent full-stack replay: correct final deck and compartment, adjacent
top-card moves, card conservation, and no plan longer than its fallback.

**Decision: no clear overall winner, so all three remain available.** Beam stays
the default, but its average advantage over A* was only 0.53 moves at two seconds
and 1.33 at five seconds. At two seconds, beam beat A* on 22 cases, tied on 21,
and lost on 17; at five seconds it won three, tied three, and lost three. A
seed-clustered paired bootstrap gave a 95% interval of -1.37 to +2.57 moves for
beam's default-budget advantage, so the observed lead was not decisive. IDA*
was substantially weaker on average.

The predeclared removal rule required the lowest mean at both budgets, a positive
paired confidence interval against both alternatives, and at least 60% of
non-tied default-budget comparisons won against both. No algorithm met it.
Results describe the current implementations and settings: A* reached its
25,000-state/open-entry cap in every trial and used about 1.26 seconds on average
in the two-second tier, while beam used its full budget. Different memory limits
or machines could change the comparison. Full counts, timings, paired results,
methodology, and source hashes are in [`search-benchmark.json`](search-benchmark.json).

A*/beam paths were also checked against 80 independent six-card BFS comparisons;
memory-limited A* retained a legal fallback without claiming optimality.

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
  pattern databases, local repairs, beam search, A*, and IDA*.
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
