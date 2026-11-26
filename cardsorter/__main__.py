"""Command line: python -m cardsorter <command> ...

  demo       scan and sort a simulated deck on simulated hardware
  plan       print a plan for one deck (scan-first by default, --known for full knowledge)
  bounds     certified worst-case and mean bounds
  visualize  browser playback at http://127.0.0.1:8765
"""

import argparse
import json
import random

from .model import NAMES, letter


def _start(value):
    try:
        return letter(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _deck(args, n=52):
    if args.cards:
        return list(args.cards)
    deck = list(range(1, n + 1))
    random.Random(args.seed).shuffle(deck)
    return deck


def demo(args):
    from .controller import CardSorter
    from .hardware import SimulatedHardware, card_name

    deck = _deck(args)
    start = NAMES[args.start]
    hardware = SimulatedHardware(deck, start=start)
    state = CardSorter(hardware, start=start, optimize=args.optimize,
                       search_seconds=args.search_seconds).run()
    stages, previous = {}, 0
    for name, end in state.dealing_stages:
        stages[name] = end - previous
        previous = end
    previous = 0
    for name, end in state.plan.stages:
        stages[name] = end - previous
        previous = end
    if args.show_moves:
        for event in hardware.events:
            if event[0] == "move":
                print(f"{event[1]} -> {event[2]}: {card_name(event[3])}")
    summary = {"completed": state.completed, "movements": state.movements_confirmed,
               "start": start, "finish": start, "movement_budget": state.movement_budget,
               "strategy": state.strategy, "stage_movements": stages}
    if state.optimization is not None:
        summary["optimization"] = state.optimization
    summary.update(left_top_to_bottom=hardware.left, center_top_to_bottom=hardware.middle,
                   right_top_to_bottom=hardware.right)
    print(json.dumps(summary, indent=2))


def plan(args):
    from . import strategy_a
    from .planner import get_planner

    deck = _deck(args)
    report = {}
    if args.exact:
        moves = strategy_a.plan(deck, start=args.start, exact=True)
    elif args.known:
        moves = get_planner().plan(deck, args.start, report)
    else:
        moves = get_planner().plan_scanned(deck, args.start, report=report)
    print(f"Top first in {args.start}:", " ".join(map(str, deck)))
    for name, value in report.items():
        if name != "best":
            print(f"  {name:22s} {value[0]:4d} -> {value[1]:4d} after polishing")
    best = f" (best: {report['best']})" if "best" in report else ""
    print(f"Verified adjacent transfers: {len(moves)}{best}")
    if args.show_moves:
        for i, (s, t, card) in enumerate(moves, 1):
            print(f"{i:3d}  {s} -> {t}  card {card}")


def bounds(args):
    from . import strategy_a
    from .scan import scan_bound

    worst, mean = strategy_a.bounds(args.n, start=args.start)
    print(f"Strategy A worst case: {worst}")
    print(f"Strategy A uniform-mean ceiling: {mean} ({float(mean):.6f})")
    if args.n > 1:
        print(f"Scan-first worst case (scan moves included): "
              f"{scan_bound(args.n, 'C' if args.start == 'C' else 'L')}")


def visualize(args):
    from .visualizer import serve

    serve(port=args.port, seed=args.seed, start=NAMES[args.start])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m cardsorter", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("demo", help="scan and sort a simulated deck")
    p.add_argument("cards", type=int, nargs="*", help="deck from top to bottom (default: --seed)")
    p.add_argument("--seed", type=int, default=42, help="repeatable shuffled deck (default: 42)")
    p.add_argument("--start", type=_start, default="L", help="L, C, or R / left, center, right (default: L)")
    p.add_argument("--show-moves", action="store_true", help="print each adjacent transfer")
    p.add_argument("--optimize", action="store_true", help="try beam search for fewer moves after scanning")
    p.add_argument("--search-seconds", type=float, default=2.0, help="beam search budget, 0-30 s (default: 2)")
    p.set_defaults(run=demo)

    p = commands.add_parser("plan", help="print the plan for one deck")
    p.add_argument("cards", type=int, nargs="*", help="deck from top to bottom (default: --seed)")
    p.add_argument("--seed", type=int, default=42, help="repeatable shuffled deck (default: 42)")
    p.add_argument("--start", type=_start, default="C", help="L, C, or R (default: C)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--known", action="store_true", help="assume the whole order is known in advance")
    group.add_argument("--exact", action="store_true", help="exact search for the whole deck (small decks only)")
    p.add_argument("--show-moves", action="store_true", help="print each adjacent transfer")
    p.set_defaults(run=plan)

    p = commands.add_parser("bounds", help="certified worst-case and mean bounds")
    p.add_argument("--n", type=int, default=52, help="deck size, 1-52 (default: 52)")
    p.add_argument("--start", type=_start, default="C", help="L, C, or R (default: C)")
    p.set_defaults(run=bounds)

    p = commands.add_parser("visualize", help="browser playback of a simulated run")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--start", type=_start, default="L", help="L, C, or R (default: L)")
    p.set_defaults(run=visualize)

    args = parser.parse_args(argv)
    try:
        args.run(args)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
