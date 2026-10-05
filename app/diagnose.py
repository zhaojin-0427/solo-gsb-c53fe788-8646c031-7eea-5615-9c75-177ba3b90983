"""Open-edge localisation from continuity measurements (POST /diagnose-open).

The request reuses the /inspect board definition and the one ordered
candidate path per net.  On top of it the client submits real continuity
measurements: each record says which net was measured, between which two
layered probe cells, and whether the probes beeped ("connected") or not
("open").

Fault model
-----------
For every net **at most one path edge may be broken**; every other edge is
conductive.  A probe is a layered cell ``(x, y, layer)`` and is located on
the net's path by the full triple -- probes at ``(x, y, 0)`` and
``(x, y, 1)`` are different probes that meet only through an in-place
layer-change (via) edge.

Record adjudication (merged over every record of one net)
----------------------------------------------------------
Let a probe at path step ``p`` and one at path step ``q`` (``p < q``); the
edges "between" them are path edges ``p .. q-1``.

* a **connected** record excludes EVERY edge between its probes from the
  broken-edge candidates (none of them may be open);
* an **open** record REQUIRES the single broken edge to lie between its two
  probes (then every conductive path between the probes crosses it).

The net's candidate edges are therefore::

    (intersection of all open-record intervals)  -  (union of all
    connected-record intervals)

A break is required only when at least one open record exists.  "No break
at all" is possible only when every record is connected.  Open records
with an empty intersection (or whose surviving edges were all excluded by
connected records) contradict each other: the whole measurement set is
inconsistent, and every candidate list is reported empty.

Malformed input vs. path violations
-----------------------------------
Board/path shape errors (missing fields, bad net indices, nets without a
measurement, non-integer coordinates, ...) are rejected with HTTP 422 by
Pydantic.  Paths must first survive :func:`app.inspector.inspect_board` --
any routing violation yields HTTP 422 with the /inspect violation list
attached.  Probes are then located on the corresponding net's path; a
probe that is not a cell of that net's path is also HTTP 422.
"""
from __future__ import annotations

from fastapi import HTTPException

from .inspector import inspect_board
from .schemas import (
    DiagnoseEdge,
    DiagnoseRequest,
    DiagnoseResponse,
    NetDiagnosis,
    PathCell,
)


def diagnose_board(req: DiagnoseRequest) -> DiagnoseResponse:
    # 1) existing board validation already ran while parsing; now run the
    #    full /inspect audit -- a broken candidate path cannot be used to
    #    localise anything, so its violations make the request unprocessable
    audit = inspect_board(req)
    if audit.violations:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    "candidate paths have routing violations; see "
                    "`violations` (same content as POST /inspect)"
                ),
                "violations": [v.model_dump() for v in audit.violations],
            },
        )

    paths = [
        [(c.x, c.y, c.layer) for c in path]
        for path in req.paths
    ]

    # 2) locate every probe on its net's path.  Index by the full layered
    #    triple: (x, y, 0) and (x, y, 1) are distinct positions, and a legal
    #    path never repeats a cell, so there is at most one step per probe.
    positions: list[dict[tuple[int, int, int], int]] = []
    for path in paths:
        positions.append({cell: i for i, cell in enumerate(path)})

    # per net: collected records as (step_a, step_b, connected?)
    records: list[list[tuple[int, int, bool]]] = [[] for _ in paths]
    for m in req.measurements:
        at = positions[m.net]
        probe_a = (m.a.x, m.a.y, m.a.layer)
        probe_b = (m.b.x, m.b.y, m.b.layer)
        for probe in (probe_a, probe_b):
            if probe not in at:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"probe cell ({probe[0]}, {probe[1]}, "
                        f"layer {probe[2]}) is not on the path of net "
                        f"{m.net}"
                    ),
                )
        p, q = at[probe_a], at[probe_b]
        if p > q:  # keep probes in path order; measurement is undirected
            p, q = q, p
        records[m.net].append((p, q, m.result == "connected"))

    # 3) merge every record of each net into one candidate-edge set
    consistent = True
    net_diagnoses: list[NetDiagnosis] = []
    for k, net_records in enumerate(records):
        path = paths[k]
        open_intervals: list[tuple[int, int]] = [
            (p, q) for (p, q, connected) in net_records if not connected
        ]
        excluded: set[int] = set()  # edges ruled out by connected records
        for p, q, connected in net_records:
            if connected:
                excluded.update(range(p, q))

        break_required = bool(open_intervals)
        candidates: list[int] = []
        if break_required:
            lo = max(p for (p, _q) in open_intervals)
            hi = min(q for (_p, q) in open_intervals)
            # the single broken edge must lie inside EVERY open interval
            candidates = [
                e for e in range(lo, hi) if e not in excluded
            ]
            if not candidates:
                consistent = False

        net_diagnoses.append(
            NetDiagnosis(
                net=k,
                name=req.nets[k].name or f"N{k + 1}",
                break_required=break_required,
                candidate_edges=[
                    DiagnoseEdge(
                        step=e,
                        cells=[
                            PathCell(
                                x=path[e][0], y=path[e][1], layer=path[e][2]
                            ),
                            PathCell(
                                x=path[e + 1][0],
                                y=path[e + 1][1],
                                layer=path[e + 1][2],
                            ),
                        ],
                    )
                    # edges naturally come out sorted by path step number
                    for e in candidates
                ],
            )
        )

    # "no broken edge at all" fits only when no record demanded a break and
    # the records do not contradict each other
    no_break_possible = (
        consistent
        and all(not d.break_required for d in net_diagnoses)
    )

    return DiagnoseResponse(
        consistent=consistent,
        no_break_possible=no_break_possible,
        nets=net_diagnoses,
    )
