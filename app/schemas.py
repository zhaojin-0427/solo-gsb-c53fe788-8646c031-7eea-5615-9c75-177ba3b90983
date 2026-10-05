"""Request/response schemas for the two-layer PCB grid router."""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, model_validator

MIN_DIM = 2
MAX_DIM = 20
MIN_NETS = 1
MAX_NETS = 6
LAYERS = (0, 1)

# Paths submitted to /inspect are user data rather than a solver answer:
# strict integers are required so that 1.0 / "1" / true do not sneak past
# the advertised "non-integer coordinates -> 422" contract.
StrictInt = Annotated[int, Field(strict=True)]


class Cell(BaseModel):
    """A grid cell on a specific layer."""

    x: int
    y: int
    layer: int = Field(ge=0, le=1)


class Pad(BaseModel):
    """A net pad: a coordinate on one of the two layers."""

    x: int
    y: int
    layer: int = Field(ge=0, le=1)


class Net(BaseModel):
    """A two-pad net with a non-negative via budget."""

    name: Optional[str] = None
    pads: list[Pad] = Field(min_length=2, max_length=2)
    via_limit: int = Field(ge=0)


class RouteRequest(BaseModel):
    width: int = Field(ge=MIN_DIM, le=MAX_DIM)
    height: int = Field(ge=MIN_DIM, le=MAX_DIM)
    blocked: list[Cell] = Field(default_factory=list)
    nets: list[Net] = Field(min_length=MIN_NETS, max_length=MAX_NETS)

    @model_validator(mode="after")
    def _check_geometry(self) -> "RouteRequest":
        for c in self.blocked:
            if not (0 <= c.x < self.width and 0 <= c.y < self.height):
                raise ValueError(
                    f"blocked cell ({c.x}, {c.y}) out of bounds for "
                    f"{self.width}x{self.height} grid"
                )
        blocked = {(c.x, c.y, c.layer) for c in self.blocked}
        seen: set[tuple[int, int, int]] = set()
        for i, net in enumerate(self.nets):
            for p in net.pads:
                key = (p.x, p.y, p.layer)
                if not (0 <= p.x < self.width and 0 <= p.y < self.height):
                    raise ValueError(
                        f"net {i} pad ({p.x}, {p.y}) out of bounds for "
                        f"{self.width}x{self.height} grid"
                    )
                if key in blocked:
                    raise ValueError(
                        f"net {i} pad ({p.x}, {p.y}, layer {p.layer}) "
                        f"is on a blocked cell"
                    )
                if key in seen:
                    raise ValueError(
                        f"duplicate pad at ({p.x}, {p.y}, layer {p.layer})"
                    )
                seen.add(key)
        return self


class PathCell(BaseModel):
    x: int
    y: int
    layer: int


class ViaPoint(BaseModel):
    x: int
    y: int


class NetResult(BaseModel):
    name: str
    path: list[PathCell]
    vias: list[ViaPoint]
    via_count: int
    move_count: int


class RouteResponse(BaseModel):
    # "optimal"  : proved best (min total vias, then min total moves)
    # "feasible" : time limit hit, best solution found so far (not proved)
    # "infeasible": proved that no routing exists
    # "unknown"  : time limit hit before any feasible solution was found
    status: str
    solve_time_seconds: float
    total_vias: Optional[int] = None
    total_moves: Optional[int] = None
    nets: Optional[list[NetResult]] = None


# ------------------------------- POST /inspect ------------------------------


class InspectCell(BaseModel):
    """One occupied cell of a candidate path (no domain restrictions:

    out-of-bounds coordinates and non-0/1 layers are reported as routing
    violations with HTTP 200 instead of being rejected as malformed input).
    """

    x: StrictInt
    y: StrictInt
    layer: StrictInt


# a cell reported inside a violation: unrestricted, since violations can
# point at out-of-bounds coordinates or illegal layer numbers
class ViolationCell(BaseModel):
    x: int
    y: int
    layer: int


class InspectRequest(RouteRequest):
    """Board definition (identical to /route) plus one candidate path per
    net, ordered like ``nets``."""

    paths: list[list[InspectCell]] = Field(min_length=MIN_NETS, max_length=MAX_NETS)

    @model_validator(mode="after")
    def _check_paths(self) -> "InspectRequest":
        if len(self.paths) != len(self.nets):
            raise ValueError(
                f"number of paths ({len(self.paths)}) must match number of "
                f"nets ({len(self.nets)})"
            )
        # a simple path over both layers can visit each board cell at most
        # once, so anything longer than the total board cell count cannot
        # possibly be legal and is rejected as malformed input
        limit = 2 * self.width * self.height
        for i, path in enumerate(self.paths):
            if len(path) > limit:
                raise ValueError(
                    f"path {i} has {len(path)} steps, more than the "
                    f"{limit} cells of a {self.width}x{self.height} board"
                )
        return self


class InspectViolation(BaseModel):
    # stable machine-readable rule identifier (see README for the list)
    rule: str
    # indices of the nets involved, in net order: one entry for a single-net
    # rule, the ordered pair (i, j) with i < j for a cross-net rule
    nets: list[int]
    # for each entry of `nets`, the sorted 0-based path step indices that
    # participate in the violation (may be empty, e.g. an empty path)
    steps: list[list[int]]
    # the cells the violation is about; for cross-net rules ordered to match
    # `nets`, canonically ordered otherwise
    cells: list[ViolationCell]
    via_count: Optional[int] = None
    via_limit: Optional[int] = None


class InspectResponse(BaseModel):
    # true only when no rule was violated
    legal: bool
    violations: list[InspectViolation]


# ----------------------------- POST /diagnose-open ---------------------------


class DiagnoseCell(BaseModel):
    """A probe position: a board cell on a specific layer.

    Like /inspect path cells, coordinates are strict integers; a probe at
    (x, y, 0) and one at (x, y, 1) are two DIFFERENT probes.
    """

    x: StrictInt
    y: StrictInt
    layer: StrictInt


class Measurement(BaseModel):
    """One continuity measurement on one net, taken between two probes.

    result == "connected" means the two probes beep together; result ==
    "open" (断开) means they do not.
    """

    # index of the measured net in the request's `nets` order
    net: StrictInt
    a: DiagnoseCell
    b: DiagnoseCell
    result: Literal["connected", "open"]


class DiagnoseRequest(InspectRequest):
    """Board definition + candidate paths (identical to /inspect) plus the
    real-world continuity measurements used to localise an open edge."""

    measurements: list[Measurement] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_measurements(self) -> "DiagnoseRequest":
        n_nets = len(self.nets)
        seen_nets: set[int] = set()
        for m in self.measurements:
            if not (0 <= m.net < n_nets):
                raise ValueError(
                    f"measurement refers to net {m.net}, but only "
                    f"{n_nets} nets are defined (valid indices 0..{n_nets - 1})"
                )
            seen_nets.add(m.net)
        # every net must carry at least one real measurement
        missing = sorted(set(range(n_nets)) - seen_nets)
        if missing:
            raise ValueError(
                f"every net needs at least one measurement; missing "
                f"measurement(s) for net(s) {missing}"
            )
        return self


class DiagnoseEdge(BaseModel):
    """One candidate broken (open) edge of a net's path."""

    # step index of the edge within the path: it joins path[step] to
    # path[step + 1] (a same-layer move or an in-place layer change)
    step: int
    # the two endpoint cells, in path order
    cells: list[PathCell]


class NetDiagnosis(BaseModel):
    # index of the net in `nets` order
    net: int
    # the net's name when one was supplied, otherwise the default N{k+1}
    name: str
    # true iff at least one "open" record forces a broken edge on this net;
    # a net with only "connected" records never needs a break
    break_required: bool
    # every single edge whose break would explain ALL of this net's records
    # at once; empty when break_required is false or the records contradict
    # each other (a shared global `consistent` flag reports that case)
    candidate_edges: list[DiagnoseEdge]


class DiagnoseResponse(BaseModel):
    # true iff the whole measurement set is self-consistent under the
    # "at most one broken edge per net" hypothesis; when false, each
    # contradicting net's candidate list is empty while the other nets
    # still report their own independently-derived candidates
    consistent: bool
    # true iff "no broken edge anywhere" explains every record -- possible
    # only when every record is "connected" (and no records contradict)
    no_break_possible: bool
    # one entry per net, in net order
    nets: list[NetDiagnosis]
