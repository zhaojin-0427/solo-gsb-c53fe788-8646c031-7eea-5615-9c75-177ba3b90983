"""Tests for POST /diagnose-open: single-open-edge localisation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def net(p0, p1, via_limit=0, name=None):
    d = {"pads": [p0, p1], "via_limit": via_limit}
    if name is not None:
        d["name"] = name
    return d


def diagnose(body):
    return client.post("/diagnose-open", json=body)


def diag(body):
    r = diagnose(body)
    assert r.status_code == 200, r.text
    return r.json()


def straight_board(**over):
    body = {
        "width": 5,
        "height": 3,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 4, "y": 0, "layer": 0}, name="N1")],
        "paths": [[{"x": x, "y": 0, "layer": 0} for x in range(5)]],
    }
    body.update(over)
    return body


def meas(p, q, result, k=0):
    def cell(step):
        return {"x": step, "y": 0, "layer": 0}
    return {"net": k, "a": cell(p), "b": cell(q), "result": result}


def edges_of(net_result):
    return [
        (e["step"],
         (e["cells"][0]["x"], e["cells"][0]["y"], e["cells"][0]["layer"]),
         (e["cells"][1]["x"], e["cells"][1]["y"], e["cells"][1]["layer"]))
        for e in net_result["candidate_edges"]
    ]


# ----------------------------- basic localisation ---------------------------

def test_open_whole_path_offers_every_edge():
    body = straight_board(measurements=[meas(0, 4, "open")])
    resp = diag(body)
    assert resp["consistent"] is True
    assert resp["no_break_possible"] is False
    n = resp["nets"][0]
    assert n["net"] == 0 and n["name"] == "N1"
    assert n["break_required"] is True
    assert [e[0] for e in edges_of(n)] == [0, 1, 2, 3]


def test_connected_excludes_open_localises_single_edge():
    # connected on 0..2 and 3..4, open end-to-end: only edge 2 fits
    body = straight_board(measurements=[
        meas(0, 2, "connected"),
        meas(0, 4, "open"),
        meas(3, 4, "connected"),
    ])
    resp = diag(body)
    n = resp["nets"][0]
    assert edges_of(n) == [
        (2, (2, 0, 0), (3, 0, 0)),
    ]


def test_two_open_records_intersect():
    # open 0..3 and open 2..4 -> the break must lie in edges {2}
    body = straight_board(measurements=[
        meas(0, 3, "open"),
        meas(2, 4, "open"),
    ])
    resp = diag(body)
    assert [e[0] for e in edges_of(resp["nets"][0])] == [2]


def test_measurement_direction_is_ignored():
    # probes given in reverse path order: same interval, same answer
    body = straight_board(measurements=[
        meas(2, 0, "connected"),
        meas(4, 0, "open"),
        meas(4, 3, "connected"),
    ])
    resp = diag(body)
    assert [e[0] for e in edges_of(resp["nets"][0])] == [2]


def test_all_connected_no_break_possible():
    body = straight_board(measurements=[
        meas(0, 2, "connected"),
        meas(2, 4, "connected"),
    ])
    resp = diag(body)
    assert resp["consistent"] is True
    assert resp["no_break_possible"] is True
    n = resp["nets"][0]
    assert n["break_required"] is False
    assert n["candidate_edges"] == []


def test_open_and_connected_overlapping_range():
    # connected 0..1 rules out edge 0; open 0..3 leaves edges 1,2
    body = straight_board(measurements=[
        meas(0, 1, "connected"),
        meas(0, 3, "open"),
    ])
    resp = diag(body)
    assert resp["no_break_possible"] is False
    assert [e[0] for e in edges_of(resp["nets"][0])] == [1, 2]


# --------------------------- layer-aware probe logic ------------------------

VIA_PATH = [
    {"x": 0, "y": 0, "layer": 0},  # step 0
    {"x": 1, "y": 0, "layer": 0},  # step 1
    {"x": 1, "y": 0, "layer": 1},  # step 2 (via edge e1 joins 1-2)
    {"x": 2, "y": 0, "layer": 1},  # step 3
    {"x": 2, "y": 0, "layer": 0},  # step 4
]


def via_board(**over):
    body = {
        "width": 3,
        "height": 3,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 2, "y": 0, "layer": 0}, via_limit=2)],
        "paths": [VIA_PATH],
    }
    body.update(over)
    return body


def test_same_coordinate_two_layers_are_distinct_probes():
    # open exactly between (1,0,0) and (1,0,1): only the via edge e1
    body = via_board(measurements=[{
        "net": 0,
        "a": {"x": 1, "y": 0, "layer": 0},
        "b": {"x": 1, "y": 0, "layer": 1},
        "result": "open",
    }])
    resp = diag(body)
    n = resp["nets"][0]
    assert edges_of(n) == [
        (1, (1, 0, 0), (1, 0, 1)),
    ]


def test_layer_change_edge_is_not_confused_with_a_cell():
    # connected across the via excludes e1; open end-to-end leaves moves
    body = via_board(measurements=[
        {"net": 0,
         "a": {"x": 1, "y": 0, "layer": 0},
         "b": {"x": 1, "y": 0, "layer": 1},
         "result": "connected"},
        {"net": 0,
         "a": {"x": 0, "y": 0, "layer": 0},
         "b": {"x": 2, "y": 0, "layer": 0},
         "result": "open"},
    ])
    resp = diag(body)
    assert [e[0] for e in edges_of(resp["nets"][0])] == [0, 2, 3]


def test_probe_on_wrong_layer_at_same_coordinate_is_off_path():
    # path never visits (0,0,1): the layer-0 cell exists at that coordinate
    # but the other layer is a different probe and must not match
    body = via_board(measurements=[{
        "net": 0,
        "a": {"x": 0, "y": 0, "layer": 1},
        "b": {"x": 2, "y": 0, "layer": 0},
        "result": "open",
    }])
    r = diagnose(body)
    assert r.status_code == 422
    assert "(0, 0, layer 1) is not on the path of net 0" in r.text


# ------------------------------- conflicts ----------------------------------

def test_disjoint_open_intervals_are_inconsistent():
    body = straight_board(measurements=[
        meas(0, 1, "open"),   # break would have to be edge 0
        meas(3, 4, "open"),   # ... and edge 3 at the same time
    ])
    resp = diag(body)
    assert resp["consistent"] is False
    assert resp["no_break_possible"] is False
    n = resp["nets"][0]
    assert n["break_required"] is True
    assert n["candidate_edges"] == []


def test_open_record_fully_excluded_by_connected_records_conflicts():
    # every edge of the open interval is known good: impossible single break
    # connected 0..2 -> edges {0,1} good; connected 2..3 -> edge 2 good;
    # open 1..3 would need a break in {1,2}: nothing survives
    body = straight_board(measurements=[
        meas(0, 2, "connected"),
        meas(2, 3, "connected"),
        meas(1, 3, "open"),
    ])
    resp = diag(body)
    assert resp["consistent"] is False
    assert resp["nets"][0]["candidate_edges"] == []


def test_identical_probe_open_is_inconsistent():
    # an open record between a point and itself can never be one edge break
    body = straight_board(measurements=[meas(2, 2, "open")])
    resp = diag(body)
    assert resp["consistent"] is False
    assert resp["nets"][0]["candidate_edges"] == []


def test_identical_probe_connected_is_neutral():
    body = straight_board(measurements=[
        meas(2, 2, "connected"),
        meas(0, 4, "open"),
    ])
    resp = diag(body)
    assert resp["consistent"] is True
    assert [e[0] for e in edges_of(resp["nets"][0])] == [0, 1, 2, 3]


# --------------------------------- multi-net --------------------------------

def two_net_board():
    return {
        "width": 4,
        "height": 3,
        "nets": [
            net({"x": 0, "y": 0, "layer": 0}, {"x": 3, "y": 0, "layer": 0},
                name="N1"),
            net({"x": 0, "y": 2, "layer": 0}, {"x": 3, "y": 2, "layer": 0},
                name="N2"),
        ],
        "paths": [
            [{"x": x, "y": 0, "layer": 0} for x in range(4)],
            [{"x": x, "y": 2, "layer": 0} for x in range(4)],
        ],
    }


def test_nets_are_adjudicated_independently():
    body = two_net_board()
    body["measurements"] = [
        # net 0: open end-to-end, connected 0..1 -> edges {1,2}
        {"net": 0, "a": {"x": 0, "y": 0, "layer": 0},
         "b": {"x": 3, "y": 0, "layer": 0}, "result": "open"},
        {"net": 0, "a": {"x": 0, "y": 0, "layer": 0},
         "b": {"x": 1, "y": 0, "layer": 0}, "result": "connected"},
        # net 1: everything beeps -> no break possible there
        {"net": 1, "a": {"x": 0, "y": 2, "layer": 0},
         "b": {"x": 3, "y": 2, "layer": 0}, "result": "connected"},
    ]
    resp = diag(body)
    assert resp["consistent"] is True
    assert resp["no_break_possible"] is False
    n0, n1 = resp["nets"]
    assert (n0["net"], n0["name"], n0["break_required"]) == (0, "N1", True)
    assert [e["step"] for e in n0["candidate_edges"]] == [1, 2]
    assert (n1["net"], n1["name"], n1["break_required"]) == (1, "N2", False)
    assert n1["candidate_edges"] == []


def test_default_net_names():
    body = two_net_board()
    del body["nets"][0]["name"]
    del body["nets"][1]["name"]
    body["measurements"] = [
        {"net": 0, "a": {"x": 0, "y": 0, "layer": 0},
         "b": {"x": 3, "y": 0, "layer": 0}, "result": "connected"},
        {"net": 1, "a": {"x": 0, "y": 2, "layer": 0},
         "b": {"x": 3, "y": 2, "layer": 0}, "result": "connected"},
    ]
    resp = diag(body)
    assert [n["name"] for n in resp["nets"]] == ["N1", "N2"]
    assert len(resp["nets"]) == 2


def test_conflict_on_one_net_does_not_wipe_other_net_candidates():
    # per-net fault hypothesis: net 0 contradicts itself, net 1 still has
    # localisable candidates; the global flag reports the inconsistency
    body = two_net_board()
    body["measurements"] = [
        {"net": 0, "a": {"x": 0, "y": 0, "layer": 0},
         "b": {"x": 1, "y": 0, "layer": 0}, "result": "open"},
        {"net": 0, "a": {"x": 2, "y": 0, "layer": 0},
         "b": {"x": 3, "y": 0, "layer": 0}, "result": "open"},
        {"net": 1, "a": {"x": 0, "y": 2, "layer": 0},
         "b": {"x": 3, "y": 2, "layer": 0}, "result": "open"},
    ]
    resp = diag(body)
    assert resp["consistent"] is False
    assert resp["no_break_possible"] is False
    assert resp["nets"][0]["candidate_edges"] == []
    assert [e["step"] for e in resp["nets"][1]["candidate_edges"]] == [0, 1, 2]


# ----------------------------------- 422 ------------------------------------

def test_422_missing_measurements():
    body = straight_board()
    assert diagnose(body).status_code == 422


def test_422_empty_measurements():
    body = straight_board(measurements=[])
    assert diagnose(body).status_code == 422


@pytest.mark.parametrize("bad_net", [-1, 2, 99])
def test_422_illegal_net_index(bad_net):
    body = straight_board(measurements=[
        {"net": bad_net,
         "a": {"x": 0, "y": 0, "layer": 0},
         "b": {"x": 4, "y": 0, "layer": 0}, "result": "open"},
    ])
    assert diagnose(body).status_code == 422


def test_422_net_without_any_measurement():
    body = two_net_board()
    body["measurements"] = [
        {"net": 0, "a": {"x": 0, "y": 0, "layer": 0},
         "b": {"x": 3, "y": 0, "layer": 0}, "result": "connected"},
    ]
    r = diagnose(body)
    assert r.status_code == 422
    assert "missing" in r.text and "1" in r.text


@pytest.mark.parametrize("bad_result", ["short", "OPEN", "", True, None])
def test_422_bad_result_value(bad_result):
    body = straight_board(measurements=[
        {"net": 0, "a": {"x": 0, "y": 0, "layer": 0},
         "b": {"x": 4, "y": 0, "layer": 0}, "result": bad_result},
    ])
    assert diagnose(body).status_code == 422


@pytest.mark.parametrize("bad_probe", [
    {"x": 1.0, "y": 0, "layer": 0},
    {"x": "1", "y": 0, "layer": 0},
    {"x": True, "y": 0, "layer": 0},
    {"x": None, "y": 0, "layer": 0},
    {"x": 1, "y": 0.5, "layer": 0},
    {"x": 1, "y": 0, "layer": 0.0},
])
def test_422_non_integer_probe(bad_probe):
    body = straight_board(measurements=[
        {"net": 0, "a": bad_probe,
         "b": {"x": 4, "y": 0, "layer": 0}, "result": "open"},
    ])
    assert diagnose(body).status_code == 422


def test_422_probe_missing_layer():
    body = straight_board(measurements=[
        {"net": 0, "a": {"x": 0, "y": 0},
         "b": {"x": 4, "y": 0, "layer": 0}, "result": "open"},
    ])
    assert diagnose(body).status_code == 422


def test_422_probe_not_on_its_own_path():
    # (1,1,0) exists on the board but is not on net 0's y=0 path
    body = straight_board(measurements=[
        {"net": 0, "a": {"x": 1, "y": 1, "layer": 0},
         "b": {"x": 4, "y": 0, "layer": 0}, "result": "open"},
    ])
    r = diagnose(body)
    assert r.status_code == 422
    assert "is not on the path of net 0" in r.text


def test_422_probe_belongs_to_other_net_path_only():
    # (0,2,0) is on net 1's path but not on net 0's; the net index decides
    body = two_net_board()
    body["measurements"] = [
        {"net": 0, "a": {"x": 0, "y": 2, "layer": 0},
         "b": {"x": 3, "y": 0, "layer": 0}, "result": "open"},
        {"net": 1, "a": {"x": 0, "y": 2, "layer": 0},
         "b": {"x": 3, "y": 2, "layer": 0}, "result": "connected"},
    ]
    r = diagnose(body)
    assert r.status_code == 422
    assert "is not on the path of net 0" in r.text


def test_422_path_violation_attaches_inspect_violations():
    body = two_net_board()
    # illegal jump on net 0 (distance 2 in one step)
    body["paths"][0] = [
        {"x": 0, "y": 0, "layer": 0},
        {"x": 2, "y": 0, "layer": 0},
        {"x": 3, "y": 0, "layer": 0},
    ]
    body["measurements"] = [
        {"net": 0, "a": {"x": 0, "y": 0, "layer": 0},
         "b": {"x": 3, "y": 0, "layer": 0}, "result": "connected"},
        {"net": 1, "a": {"x": 0, "y": 2, "layer": 0},
         "b": {"x": 3, "y": 2, "layer": 0}, "result": "connected"},
    ]
    r = diagnose(body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert "violations" in detail
    rules = [v["rule"] for v in detail["violations"]]
    assert "NON_ORTHOGONAL_STEP" in rules
    # the attached violations are exactly what /inspect would return
    inspect_body = {k: v for k, v in body.items() if k != "measurements"}
    inspect_resp = client.post("/inspect", json=inspect_body).json()
    assert detail["violations"] == inspect_resp["violations"]


def test_422_path_violation_takes_precedence_over_probe_check():
    # both an illegal path and an off-path probe are present: the path audit
    # fires first and its violations are the 422 detail
    body = straight_board(measurements=[
        {"net": 0, "a": {"x": 1, "y": 2, "layer": 0},
         "b": {"x": 4, "y": 0, "layer": 0}, "result": "open"},
    ])
    body["paths"] = [[
        {"x": 0, "y": 0, "layer": 0},
        {"x": 2, "y": 0, "layer": 0},
        {"x": 4, "y": 0, "layer": 0},
    ]]
    r = diagnose(body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert any(v["rule"] == "NON_ORTHOGONAL_STEP"
               for v in detail["violations"])


def test_422_blocked_path_cell_attaches_blocked_violation():
    body = straight_board(measurements=[meas(0, 4, "open")])
    body["blocked"] = [{"x": 2, "y": 0, "layer": 0}]
    r = diagnose(body)
    assert r.status_code == 422
    rules = [v["rule"] for v in r.json()["detail"]["violations"]]
    assert "BLOCKED_CELL" in rules


def test_422_board_validation_inherited():
    # pad on a blocked cell is a board-level 422 just like /route /inspect
    body = straight_board(measurements=[meas(0, 4, "open")])
    body["blocked"] = [{"x": 0, "y": 0, "layer": 0}]
    assert diagnose(body).status_code == 422


def test_422_path_count_mismatch():
    body = straight_board(measurements=[meas(0, 4, "open")])
    body["paths"] = []
    assert diagnose(body).status_code == 422


# --------------------------- response shape/order ---------------------------

def test_response_shape_and_edge_step_ordering():
    # several candidates must come out sorted by path step, endpoints in
    # path order
    body = straight_board(measurements=[
        meas(0, 4, "open"),
        meas(0, 1, "connected"),
        meas(3, 4, "connected"),
    ])
    resp = diag(body)
    edges = resp["nets"][0]["candidate_edges"]
    steps = [e["step"] for e in edges]
    assert steps == sorted(steps) == [1, 2]
    for e in edges:
        a, b = e["cells"]
        assert e["step"] >= 0
        # endpoint cells are full layered cells
        assert set(a) == {"x", "y", "layer"}
        assert set(b) == {"x", "y", "layer"}
    assert set(resp) == {"consistent", "no_break_possible", "nets"}
    assert set(resp["nets"][0]) == {
        "net", "name", "break_required", "candidate_edges",
    }
    assert set(edges[0]) == {"step", "cells"}


def test_accepts_solver_then_inspect_legal_routing():
    # a real /route answer fed straight into /diagnose-open must be legal
    board = {
        "width": 8, "height": 8,
        "blocked": [{"x": 3, "y": y, "layer": 0} for y in range(8)],
        "nets": [
            net({"x": 0, "y": 3, "layer": 0}, {"x": 7, "y": 3, "layer": 0}, 2),
            net({"x": 0, "y": 5, "layer": 1}, {"x": 7, "y": 5, "layer": 1}, 0),
        ],
    }
    solved = client.post("/route", json=board).json()
    assert solved["status"] in ("optimal", "feasible")
    paths = [n["path"] for n in solved["nets"]]
    p0 = paths[0]
    body = dict(board)
    body["paths"] = paths
    body["measurements"] = [
        {"net": 0, "a": p0[0], "b": p0[-1], "result": "connected"},
        {"net": 1, "a": paths[1][0], "b": paths[1][-1], "result": "connected"},
    ]
    resp = diag(body)
    assert resp["no_break_possible"] is True
    assert all(not n["break_required"] for n in resp["nets"])


# ------------------- existing endpoints stay unchanged ----------------------

def test_existing_endpoints_unchanged():
    assert client.get("/health").json() == {"status": "ok"}
    # /inspect still answers legal/violations only, with no new fields
    body = straight_board()
    r = client.post("/inspect", json=body)
    assert r.status_code == 200
    assert set(r.json()) == {"legal", "violations"}
    # /route shape unchanged
    r = client.post("/route", json={
        "width": 3, "height": 3,
        "nets": [net({"x": 1, "y": 1, "layer": 0},
                     {"x": 1, "y": 1, "layer": 1}, via_limit=1)],
    })
    assert r.status_code == 200
    assert set(r.json()) == {
        "status", "solve_time_seconds", "total_vias",
        "total_moves", "nets",
    }
