"""Open-circuit diagnosis from continuity measurements (POST /diagnose-open).

The request carries the same board definition and one ordered candidate
path per net as :func:`app.inspector.inspect_board`, plus at least one
real continuity measurement per net.  Each measurement names a net and
two **layer-aware** probe cells on that net's path and states whether
the meter reads continuity or open::

    measurement(net k, probes a, b, connected=True):
        no open edge may lie on the path segment a .. b
    measurement(net k, probes a, b, connected=False):
        the open edge must lie on the path segment a .. b
        (when the two probes are the same path cell there is no edge on
        the segment, so such a record can never be explained)

Per net the hypothesis is **at most one open path edge**; different nets
are diagnosed independently.  Crossing (overlapping) measurements on the
same net are merged by interval arbitration:

* the allowed set starts with every edge of the path (one fault may sit
  anywhere);
* every *open* reading intersects it with the edges between its probes;
* every *continuity* reading subtracts the edges between its probes.

What remains is the list of candidate open edges, sorted by path step.
When every reading is a continuity reading the allowed set is never
intersected, so the hypothesis that the net has **no** open edge is also
possible (``no_break_possible``); any open reading rules that hypothesis
out.  An empty candidate set with open readings means the records
contradict each other under the single-fault hypothesis.

A path edge is either a same-layer orthogonal move or an in-place layer
change (a via); both are breakable edges of the *layer-aware* path, so a
layer-0 probe and a layer-1 probe at the same (x, y) are distinct probe
points straddling the via edge rather than one grid point.

The request is rejected with HTTP 422 (never an /inspect-style 200
violation report) when a net index is unknown, a probe is not a cell of
its net's path, a net has no measurement, or a candidate path violates
any routing rule -- the latter case attaches the full /inspect report.
"""
from __future__ import annotations

from .inspector import inspect_board
from .schemas import (
    BrokenEdge,
    DiagnoseRequest,
    DiagnoseResponse,
    NetDiagnosis,
    PathCell,
)

# machine-readable reason codes carried in the 422 detail objects
REASON_PATH_VIOLATIONS = "path_violations"
REASON_UNKNOWN_NET = "unknown_net"
REASON_PROBE_NOT_ON_PATH = "probe_not_on_path"
REASON_NO_MEASUREMENTS = "no_measurements"


class DiagnoseValidationError(Exception):
    """The diagnose request is malformed -> HTTP 422.

    ``errors`` is a list of JSON-serialisable detail objects; the path
    violations entry, when present, carries the full /inspect report.
    """

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__(f"{len(errors)} diagnose validation error(s)")


def _probe(cell) -> tuple[int, int, int]:
    return (cell.x, cell.y, cell.layer)


def diagnose_board(req: DiagnoseRequest) -> DiagnoseResponse:
    # ---- stage 1: the candidate paths must be exactly as legal as for
    # /inspect; every routing violation is a 422 here, with the report ---
    report = inspect_board(req)
    if not report.legal:
        raise DiagnoseValidationError([
            {
                "reason": REASON_PATH_VIOLATIONS,
                "msg": "candidate paths violate routing rules; see violations",
                "violations": [v.model_dump() for v in report.violations],
            }
        ])

    n_nets = len(req.nets)
    paths = [
        [(c.x, c.y, c.layer) for c in path]
        for path in req.paths
    ]

    # ---- stage 2: locate every probe on its net's ordered path ---------
    # net -> list of (lo, hi, connected), with lo <= hi path-step indices
    located: dict[int, list[tuple[int, int, bool]]] = {
        k: [] for k in range(n_nets)
    }
    errors: list[dict] = []
    for m, rec in enumerate(req.measurements):
        if not 0 <= rec.net < n_nets:
            errors.append({
                "reason": REASON_UNKNOWN_NET,
                "measurement": m,
                "net": rec.net,
                "msg": (
                    f"measurement {m} references net {rec.net}, "
                    f"valid net indices are 0..{n_nets - 1}"
                ),
            })
            continue
        path = paths[rec.net]
        positions = {cell: i for i, cell in enumerate(path)}
        probes: list[tuple[int, int, int] | None] = []
        for side, cell in (("a", rec.a), ("b", rec.b)):
            point = _probe(cell)
            idx = positions.get(point)
            if idx is None:
                errors.append({
                    "reason": REASON_PROBE_NOT_ON_PATH,
                    "measurement": m,
                    "net": rec.net,
                    "probe": side,
                    "cell": {"x": point[0], "y": point[1], "layer": point[2]},
                    "msg": (
                        f"measurement {m} probe '{side}' at "
                        f"({point[0]}, {point[1]}, layer {point[2]}) is not "
                        f"a cell of net {rec.net}'s candidate path"
                    ),
                })
            probes.append(point if idx is not None else None)
        if probes[0] is not None and probes[1] is not None:
            ia, ib = positions[probes[0]], positions[probes[1]]
            located[rec.net].append((min(ia, ib), max(ia, ib), rec.connected))

    # a net without any usable record cannot be diagnosed; the request
    # contract requires at least one real measurement per net
    for k in range(n_nets):
        if not located[k]:
            errors.append({
                "reason": REASON_NO_MEASUREMENTS,
                "net": k,
                "msg": f"net {k} has no valid measurement record",
            })

    if errors:
        raise DiagnoseValidationError(errors)

    # ---- stage 3: per-net interval arbitration -------------------------
    results: list[NetDiagnosis] = []
    for k, net in enumerate(req.nets):
        records = located[k]
        path = paths[k]
        # edge index s (the edge path[s] -> path[s+1]) starts as a
        # candidate; open readings intersect, continuity readings remove
        allowed: set[int] | None = None  # None == "every edge"
        no_break = True
        for lo, hi, connected in records:
            segment = set(range(lo, hi))
            if connected:
                if segment:
                    if allowed is None:
                        allowed = set(range(len(path) - 1))
                    allowed -= segment
            else:
                no_break = False
                allowed = segment if allowed is None else allowed & segment
        candidates = (
            sorted(allowed)
            if allowed is not None
            else list(range(len(path) - 1))
        )
        results.append(
            NetDiagnosis(
                name=net.name or f"N{k + 1}",
                no_break_possible=no_break,
                candidates=[
                    BrokenEdge(
                        step=s,
                        cells=[
                            PathCell(
                                x=path[s][0], y=path[s][1], layer=path[s][2]
                            ),
                            PathCell(
                                x=path[s + 1][0],
                                y=path[s + 1][1],
                                layer=path[s + 1][2],
                            ),
                        ],
                    )
                    for s in candidates
                ],
            )
        )

    return DiagnoseResponse(nets=results)
