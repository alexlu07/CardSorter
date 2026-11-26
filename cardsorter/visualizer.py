"""Local browser playback of simulated sorter events (python -m cardsorter visualize)."""

import json
from pathlib import Path
import random
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .controller import CardSorter
from .hardware import SimulatedHardware


def validate_deck(deck):
    if not isinstance(deck, list):
        raise ValueError("Custom deck must be a list of card IDs")
    if any(type(card) is not int or not 1 <= card <= 52 for card in deck):
        raise ValueError("Every card must be an integer from 1 to 52")
    duplicates = sorted({card for card in deck if deck.count(card) > 1})
    missing = sorted(set(range(1, 53)) - set(deck))
    if len(deck) != 52 or duplicates or missing:
        details = [f"Expected 52 cards; received {len(deck)}"]
        if duplicates:
            details.append("duplicates: " + ", ".join(map(str, duplicates)))
        if missing:
            details.append("missing: " + ", ".join(map(str, missing)))
        raise ValueError("; ".join(details))
    return deck.copy()


def simulation(seed=None, start="left", *, deck=None, optimize=False, search_seconds=2.0):
    if type(optimize) is not bool:
        raise ValueError("Optimize must be true or false")
    custom = deck is not None
    if custom:
        deck = validate_deck(deck)
    else:
        deck = list(range(1, 53))
        random.Random(seed).shuffle(deck)
    hardware = SimulatedHardware(deck, start=start)
    state = CardSorter(hardware, start=start, optimize=optimize, search_seconds=search_seconds).run()
    expected = [(), (), ()]
    expected[("left", "center", "right").index(start)] = tuple(range(1, 53))
    if state.stacks != tuple(expected):
        raise RuntimeError("Simulation failed to finish sorted")
    stages = []
    stage_start = 0
    for name, end in state.dealing_stages:
        stages.append({"name": name, "start": stage_start, "end": end})
        stage_start = end
    offset = state.initial_deal.confirmed_moves
    stage_start = offset
    for name, end in state.plan.stages:
        stages.append({"name": name, "start": stage_start, "end": offset + end})
        stage_start = offset + end
    events = []
    for event in hardware.events:
        if event[0] == "scan":
            events.append({"kind": "scan", "card": event[1]})
        elif event[0] == "move":
            events.append({"kind": "move", "source": event[1], "destination": event[2], "card": event[3]})
    return {"api_version": 5, "seed": None if custom else str(seed), "shuffle_mode": "custom" if custom else "seeded",
            "deck": deck, "events": events, "stages": stages,
            "movements": state.movements_confirmed, "start": start, "finish": start,
            "movement_budget": state.movement_budget, "optimization": state.optimization,
            "strategy": state.strategy, "scans": sum(event["kind"] == "scan" for event in events)}


class Handler(BaseHTTPRequestHandler):
    default_seed = 42
    default_start = "left"

    def do_POST(self):
        if urlsplit(self.path).path != "/api/simulation":
            self.respond(404, b"Not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError("Simulation request must be 1–8192 bytes")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or "deck" not in request:
                raise ValueError("Expected an object containing a custom deck")
            # Validate before simulation, including null, which is not a deck.
            deck = validate_deck(request["deck"])
            start = request.get("start", self.default_start)
            if start not in ("left", "center", "right"):
                raise ValueError("Start must be left, center, or right")
            payload = simulation(start=start, deck=deck, optimize=request.get("optimize", False),
                                 search_seconds=request.get("search_seconds", 2.0))
        except (ValueError, UnicodeDecodeError) as error:
            self.respond(400, json.dumps({"error": str(error)}).encode(), "application/json")
            return
        except Exception:
            traceback.print_exc()
            self.respond(500, b'{"error":"Simulation failed; see server output"}', "application/json")
            return
        self.respond(200, json.dumps(payload).encode(), "application/json")

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path == "/api/simulation":
            try:
                params = parse_qs(request.query)
                raw = params.get("seed", [str(self.default_seed)])[0]
                if len(raw) > 20:
                    raise ValueError("Seed must be an integer of at most 20 characters")
                seed = int(raw)
                start = params.get("start", [self.default_start])[0]
                if start not in ("left", "center", "right"):
                    raise ValueError("Start must be left, center, or right")
                optimize = params.get("optimize", ["false"])[0]
                if optimize not in ("true", "false"):
                    raise ValueError("Optimize must be true or false")
                search_seconds = float(params.get("search_seconds", ["2"])[0])
                payload = simulation(seed, start=start, optimize=optimize == "true",
                                     search_seconds=search_seconds)
            except ValueError as error:
                self.respond(400, json.dumps({"error": str(error)}).encode(), "application/json")
                return
            except Exception:
                traceback.print_exc()
                self.respond(500, b'{"error":"Simulation failed; see server output"}', "application/json")
                return
            self.respond(200, json.dumps(payload).encode(), "application/json")
        elif request.path in ("/", "/index.html"):
            self.respond(200, Path(__file__).with_name("visualizer.html").read_bytes(), "text/html; charset=utf-8")
        elif request.path == "/favicon.ico":
            self.respond(204, b"", "image/x-icon")
        else:
            self.respond(404, b"Not found", "text/plain")

    def respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def serve(port=8765, seed=42, start="left"):
    """Serve the visualizer on http://127.0.0.1:<port> until Ctrl+C."""
    Handler.default_seed = seed
    Handler.default_start = start
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Card sorter visualizer: http://127.0.0.1:{server.server_port}", flush=True)
        print("Press Ctrl+C to stop. All cards and motors are simulated.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
