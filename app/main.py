"""FastAPI entrypoint for the two-layer PCB grid router."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .diagnoser import DiagnoseValidationError, diagnose_board
from .inspector import inspect_board
from .schemas import (
    DiagnoseRequest,
    DiagnoseResponse,
    InspectRequest,
    InspectResponse,
    RouteRequest,
    RouteResponse,
)
from .solver import solve_board

app = FastAPI(
    title="Two-Layer PCB Grid Router",
    version="1.0.0",
    description=(
        "Jointly routes two-pad nets on a two-layer grid board with "
        "OR-Tools CP-SAT. Minimises total vias first, then total "
        "same-layer moves."
    ),
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    # `def` (not `async def`): the CP-SAT solve is CPU-bound, so FastAPI
    # runs it in the threadpool and the event loop stays responsive.
    return solve_board(req)


@app.post("/inspect", response_model=InspectResponse)
def inspect(req: InspectRequest) -> InspectResponse:
    # pure rule audit of the supplied candidate paths; no solving
    return inspect_board(req)


@app.post("/diagnose-open", response_model=DiagnoseResponse)
def diagnose_open(req: DiagnoseRequest) -> DiagnoseResponse:
    # audits the candidate paths first (violations are a 422 here), then
    # locates the probes and arbitrates the continuity measurements into
    # candidate open edges; pure logic, no CP-SAT solving
    try:
        return diagnose_board(req)
    except DiagnoseValidationError as exc:
        # one request can carry several bad records: report every reason
        raise HTTPException(status_code=422, detail=exc.errors)
