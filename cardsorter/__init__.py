"""Three-compartment card sorter: scan-first planning with certified move bounds.

    from cardsorter import CardSorter, SimulatedHardware, plan_scanned

    moves = plan_scanned(deck, start="C")          # at most 322 moves from C, 350 from a side
    state = CardSorter(hardware, start="left").run()

Modules: model (stacks, moves, replay), scan (phase-1 routing), planner (all candidates,
polished and verified), strategy_a / strategy_b / merge_dp (the planners), tables (exact
small-block tables), polish, improver (optional beam search), hardware, dealer, controller,
visualizer. Command line: python -m cardsorter --help.
"""

from .controller import CardSorter
from .hardware import Hardware, SimulatedHardware, card_id, card_name
from .model import Move, verify
from .planner import BOUND, plan, plan_scanned

__all__ = ["BOUND", "CardSorter", "Hardware", "Move", "SimulatedHardware", "card_id", "card_name",
           "plan", "plan_scanned", "verify"]
