# Three-compartment card sorter

The machine has three compartments in a row (left, middle, right) and moves one exposed card at a time between adjacent compartments. A left-to-right transfer counts as two moves through the middle. The camera can read only the top card of the starting compartment, so the deck order is unknown until the cards have been scanned. The sorter scans the deck as part of the sort and puts cards 1–52 back into the starting compartment, 1 on top.

| Start and finish | Route each card as it is read | Rebuild the starting pile | Guaranteed total |
|---|---|---|---:|
| **Middle** | 1–22 → left, 23–52 → right | Sort 23–52 from right onto the middle, then 1–22 from left on top | 52 + 164 + 106 = **322** |
| **Left** | 1–31 → middle, 32–52 → right through the middle | Sort 32–52 from right onto left, then 1–31 from the middle on top | 73 + 106 + 171 = **350** |

Right starts mirror left starts. If you can choose, start in the middle: it has the lower guarantee. Both totals include the scanning moves, and they equal the best certified bounds even for a planner that knows the whole order in advance.

## How it works

**Phase 1: scan and route** (`cards.ScanDealer`). The camera reads the card on top of the starting pile, and the dealer sends it to its pile by value, using only that card. From a side start, a card bound for the far side moves to the middle and waits there. Waiting cards move on only when a card bound for the middle is read, and cards still waiting at the end are left for phase 2. Scanning stops as soon as the bottom card is known by elimination; a bottom card or pair that is already in its final place never moves. An already-sorted deck therefore finishes in 100 moves from any start, the minimum for reading 51 cards.

**Phase 2: finish from the scanned layout** (`combined_sorter.Planner.plan_scanned`). Every card is now known. Cards still waiting on the middle either move on to the far side (the certified route) or the far pile is gathered onto the middle above them. Then the upper pile is sorted onto the starting compartment, and the lower pile on top of it. For each pile the planner tries:

- Strategy A's certified recursive merge ([card_sorter.py](card_sorter.py), exact search for blocks of up to 11 cards), in its worst-case and mean-optimised variants, forwards and time-reversed;
- a per-deck DP over A's merge family (`MergeDP`, exact 9-card table leaves), forwards and time-reversed;
- Strategy B's per-deck hub-distribution DP ([hubsort.py](hubsort.py)), continuing the same first split.

Every combination is polished. Polishing removes pointless excursions, and replaces any window of at most 9 cards (10–11 for the best candidates) by its exact optimum when that is shorter. Phase-1 moves are never changed. The shortest plan is replayed by `card_sorter.verify` and checked against the 322 / 350 bound before any further card moves.

The guarantee comes from the first pile split plus the better of A's and B's certified block bounds: `combined_sorter.scan_bound()` computes it.

## Running it

```sh
python cards.py --demo --seed 42 --start center --show-moves
python visualizer.py
```

Open the visualizer at http://127.0.0.1:8765 to watch a seeded or custom deck being scanned and sorted. The optional `--optimize` beam search can try to shorten the phase-2 plan further.

The first run builds the exact 9-card tables. This takes about a minute and about 1 GB of RAM. The tables are then cached in `.table_cache/`, so later runs load them in seconds. Planning needs numpy and takes 1–2 seconds per deck.

## When the order is already known

`combined_sorter.plan(deck, start="C")` plans without a scanning pass: for example, if the deck order was recorded on an earlier run. It keeps all of Strategy A's certified plans (322 / 350) and adds B's per-deck DP, the merge DP and the same polishing.

```sh
python combined_sorter.py --seed 42 --start L
python card_sorter.py --start L --bounds 52
```

| Strategy A, proven bound | Middle | Left |
|---|---:|---:|
| Worst-case optimum interval | 204–322 | 206–350 |
| Reverse deck optimum | 204 | 206 |
| Uniform-shuffle mean ceiling | <276.065 | <307.750 |

[The C++ certifier](certify_blocks.cpp) reproduces the small-block constants used by the bound calculation.

## Files and API

- `cards.py`: card numbering, the `Hardware` protocol, `ScanDealer` (phase 1), simulated hardware and the CLI.
- `sorter.py`: `CardSorter(hardware, start="left").run()` scans, plans, verifies and executes the rest.
- `combined_sorter.py`: `Planner.plan_scanned` (phase 2), `scan_destination` / `scan_moves` / `scan_bound`, and the full-knowledge `plan`.
- `card_sorter.py`: Strategy A, its certified bounds and the independent `verify` replay.
- `hubsort.py`: Strategy B and the exact BFS tables.
- `heuristic_planner.py`: optional time-bounded beam search (`optimize_plan`).
- `exact_stack_planner.py`: `Move(card, source, destination)` and `apply_moves(stacks, moves, protected=...)`, which replays moves and rejects illegal ones.
- `visualizer.py`, `visualizer.html`: local simulation server and playback of scans and moves.

Lists are top-to-bottom; compartment names are `left`, `center`, `right`. IDs use clubs 1–13, diamonds 14–26, hearts 27–39, spades 40–52, with A, 2, …, 10, J, Q, K in each suit.

## Connecting hardware

The current executable simulates both scanning and motors. It does not recognize
camera images or drive real hardware. Implement the `Hardware` protocol in `cards.py`,
then run:

```python
from sorter import CardSorter

sorter = CardSorter(adapter, start="left")  # Load the deck on the left.
state = sorter.run()
```

- `scan_top()` must acquire a fresh image of the top card of the starting
  compartment and return a recognized ID, raising on ambiguous or unreadable
  cards. Keep the card stationary during capture.
- `move_one(source, destination)` must singulate one card, drive the adjacent
  roller path, confirm arrival using sensors, and stop before returning. It must
  support all four adjacent directions, enforce a bounded timeout and detect
  jams/double feeds. Encoder movement alone does not prove that a card moved.
  Both arguments are compartment names. No direct left/right jump is requested.
- `stop()` must disable every roller and remain usable after a fault. Physical
  motor control should also have a watchdog independent of this Python process.

The mechanism needs a separator/retard pad to prevent double feeds, a way to keep
the changing stack height within roller reach, and an unobstructed view of the
starting compartment's top card index. A camera cannot identify a face-down card from its back.

On any scan, planning, or transfer error, the controller requests a motor stop and
raises the error. `sorter.state` retains the phase, confirmed movement count,
initial-deal state, planned moves, and any pending sorting move. After scanning,
`state.stacks` contains the last confirmed full arrangement. During scanning,
`state.stacks` is `None`; consult `state.initial_deal` for the partial stacks
(unread cards are `None`) and its pending source, destination, and card. `source_remaining` counts source cards not yet fed;
`confirmed_moves` counts only confirmed initial transfers. If a scan fails,
`awaiting_scan` is true and no card has moved for it. Every routing move is
separately confirmed. `dealing_stages` contains scan-stage movement
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
