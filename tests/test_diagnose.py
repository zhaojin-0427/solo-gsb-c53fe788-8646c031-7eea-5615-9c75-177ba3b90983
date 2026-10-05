"""Tests for POST /diagnose-open: single open-edge diagnosis."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PATH_3X3_VIA = [
    {"x": 0, "y": 0, "layer": 0},
    {"x": 1, "y": 0, "layer": 0},
    {"x": 1, "y": 0, "layer": 1},   # edge 1: via at (1, 0)
    {"x": 1, "y": 1, "layer": 1},
    {"x": 1, "y": 2, "layer": 1},
    {"x": 1, "y": 2, "layer": 0},   # edge 4: via at (1, 2)
    {"x": 2, "y": 2, "layer": 0},
]


def net(p0, p1, via_limit=0, name=None):
    d = {"pads": [p0, p1], "via_limit": via_limit}
    if name is not None:
        d["name"] = name
    return d


def cell(x, y, layer):
    return {"x": x, "y": y, "layer": layer}


def rec(k, a, b, connected):
    return {"net": k, "a": a, "b": b, "connected": connected}


def straight_board(n=5, y=0, layer=0):
    return {
        "width": max(n, 3),
        "height": 3,
        "nets": [net(cell(0, y, layer), cell(n - 1, y, layer))],
        "paths": [[cell(x, y, layer) for x in range(n)]],
    }


def diagnose(body):
    r = client.post("/diagnose-open", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def diagnose_422(body):
    r = client.post("/diagnose-open", json=body)
    assert r.status_code == 422, r.text
    return r.json()


def steps(resp, k=0):
    return [e["step"] for e in resp["nets"][k]["candidates"]]


def edge_cells(resp, k=0):
    return [
        [(c["x"], c["y"], c["layer"]) for c in e["cells"]]
        for e in resp["nets"][k]["candidates"]
    ]


# ---------------------------- single measurements ---------------------------

def test_open_reading_on_whole_path_names_every_edge():
    body = straight_board(5)
    body["measurements"] = [rec(0, cell(0, 0, 0), cell(4, 0, 0), False)]
    resp = diagnose(body)
    assert steps(resp) == [0, 1, 2, 3]
    assert resp["nets"][0]["no_break_possible"] is False
    assert resp["nets"][0]["name"] == "N1"
    # endpoint cells of each edge follow the ordered path
    assert edge_cells(resp) == [
        [(0, 0, 0), (1, 0, 0)],
        [(1, 0, 0), (2, 0, 0)],
        [(2, 0, 0), (3, 0, 0)],
        [(3, 0, 0), (4, 0, 0)],
    ]


def test_continuity_reading_leaves_no_candidate_but_break_unneeded():
    body = straight_board(5)
    body["measurements"] = [rec(0, cell(0, 0, 0), cell(4, 0, 0), True)]
    resp = diagnose(body)
    assert steps(resp) == []
    # whole path proved continuous: the no-break hypothesis is the answer
    assert resp["nets"][0]["no_break_possible"] is True


def test_partial_continuity_leaves_untested_edges_as_candidates():
    body = straight_board(5)
    body["measurements"] = [rec(0, cell(0, 0, 0), cell(2, 0, 0), True)]
    resp = diagnose(body)
    # edges 0,1 are excluded; edges 2,3 were never tested and stay open,
    # and the net may simply be intact
    assert steps(resp) == [2, 3]
    assert resp["nets"][0]["no_break_possible"] is True


# ----------------------------- crossing arbitration -------------------------

def test_crossing_records_merge_to_one_edge():
    body = straight_board(5)
    body["measurements"] = [
        rec(0, cell(0, 0, 0), cell(3, 0, 0), True),   # edges 0,1,2 intact
        rec(0, cell(3, 0, 0), cell(4, 0, 0), False),  # open on edge 3
    ]
    resp = diagnose(body)
    assert steps(resp) == [3]
    assert resp["nets"][0]["no_break_possible"] is False


def test_open_then_continuity_overlapping_narrows_set():
    body = straight_board(5)
    body["measurements"] = [
        rec(0, cell(0, 0, 0), cell(4, 0, 0), False),  # open somewhere
        rec(0, cell(0, 0, 0), cell(2, 0, 0), True),   # not edges 0,1
    ]
    resp = diagnose(body)
    assert steps(resp) == [2, 3]
    assert resp["nets"][0]["no_break_possible"] is False


def test_measurement_direction_does_not_matter():
    body = straight_board(5)
    body["measurements"] = [
        rec(0, cell(3, 0, 0), cell(0, 0, 0), True),
        rec(0, cell(4, 0, 0), cell(3, 0, 0), False),
    ]
    resp = diagnose(body)
    assert steps(resp) == [3]


def test_conflicting_open_readings_return_empty_candidates():
    body = straight_board(5)
    body["measurements"] = [
        rec(0, cell(0, 0, 0), cell(2, 0, 0), False),  # open edge 0 or 1
        rec(0, cell(3, 0, 0), cell(4, 0, 0), False),  # open edge 3:
        #                                              disjoint segments
    ]
    resp = diagnose(body)
    assert steps(resp) == []
    assert resp["nets"][0]["no_break_possible"] is False


def test_continuity_over_whole_open_segment_is_conflict():
    body = straight_board(5)
    body["measurements"] = [
        rec(0, cell(0, 0, 0), cell(3, 0, 0), False),
        rec(0, cell(0, 0, 0), cell(3, 0, 0), True),
    ]
    resp = diagnose(body)
    assert steps(resp) == []
    assert resp["nets"][0]["no_break_possible"] is False


# ----------------------------- vias / layer probes --------------------------

def via_board():
    return {
        "width": 3,
        "height": 3,
        "nets": [
            net(cell(0, 0, 0), cell(2, 2, 0), via_limit=2),
        ],
        "paths": [PATH_3X3_VIA],
    }


def test_open_reading_across_via_nails_via_edge():
    body = via_board()
    body["measurements"] = [
        rec(0, cell(1, 0, 0), cell(1, 0, 1), False),
    ]
    resp = diagnose(body)
    assert steps(resp) == [1]
    # the broken edge is the in-place layer change: same coordinate,
    # the two layer cells are distinct path points
    assert edge_cells(resp) == [[(1, 0, 0), (1, 0, 1)]]
    assert resp["nets"][0]["no_break_possible"] is False


def test_same_coordinate_two_layer_probes_are_not_one_cell():
    body = via_board()
    # continuity across the via excludes only edge 1
    body["measurements"] = [rec(0, cell(1, 0, 0), cell(1, 0, 1), True)]
    resp = diagnose(body)
    assert steps(resp) == [0, 2, 3, 4, 5]
    assert resp["nets"][0]["no_break_possible"] is True


def test_open_segment_may_contain_moves_and_vias():
    body = via_board()
    body["measurements"] = [
        rec(0, cell(1, 0, 0), cell(1, 2, 1), False),  # edges 1,2,3
        rec(0, cell(1, 1, 1), cell(1, 2, 1), True),   # edge 3 intact
    ]
    resp = diagnose(body)
    assert steps(resp) == [1, 2]


def test_same_cell_probes_connected_is_neutral():
    body = straight_board(5)
    body["measurements"] = [rec(0, cell(2, 0, 0), cell(2, 0, 0), True)]
    resp = diagnose(body)
    # empty segment excludes nothing; with no open reading the net may
    # have no break at all, and every edge remains untested
    assert steps(resp) == [0, 1, 2, 3]
    assert resp["nets"][0]["no_break_possible"] is True


def test_same_cell_probes_open_can_never_be_explained():
    body = straight_board(5)
    body["measurements"] = [rec(0, cell(2, 0, 0), cell(2, 0, 0), False)]
    resp = diagnose(body)
    assert steps(resp) == []
    assert resp["nets"][0]["no_break_possible"] is False


# ------------------------------- multiple nets ------------------------------

def two_net_board():
    return {
        "width": 5,
        "height": 3,
        "nets": [
            net(cell(0, 0, 0), cell(4, 0, 0), name="A"),
            net(cell(0, 2, 0), cell(4, 2, 0), name="B"),
        ],
        "paths": [
            [cell(x, 0, 0) for x in range(5)],
            [cell(x, 2, 0) for x in range(5)],
        ],
    }


def test_nets_diagnosed_independently_in_net_order():
    body = two_net_board()
    body["measurements"] = [
        rec(1, cell(0, 2, 0), cell(4, 2, 0), True),   # B intact
        rec(0, cell(0, 0, 0), cell(4, 0, 0), False),  # A open somewhere
    ]
    resp = diagnose(body)
    assert [n["name"] for n in resp["nets"]] == ["A", "B"]
    assert steps(resp, 0) == [0, 1, 2, 3]
    assert resp["nets"][0]["no_break_possible"] is False
    assert steps(resp, 1) == []
    assert resp["nets"][1]["no_break_possible"] is True


# ---------------------------------- 422 -------------------------------------

def test_422_path_violation_attaches_inspect_violations():
    body = straight_board(5)
    body["paths"] = [[  # diagonal jump between steps 1 and 2
        cell(0, 0, 0), cell(1, 0, 0), cell(2, 1, 0),
        cell(3, 0, 0), cell(4, 0, 0),
    ]]
    body["measurements"] = [rec(0, cell(0, 0, 0), cell(4, 0, 0), True)]
    detail = diagnose_422(body)["detail"]
    assert len(detail) == 1
    assert detail[0]["reason"] == "path_violations"
    rules = [v["rule"] for v in detail[0]["violations"]]
    assert "NON_ORTHOGONAL_STEP" in rules


def test_422_blocked_path_cell_attaches_violation():
    body = straight_board(3)
    body["blocked"] = [cell(1, 0, 0)]
    body["measurements"] = [rec(0, cell(0, 0, 0), cell(2, 0, 0), True)]
    detail = diagnose_422(body)["detail"]
    assert detail[0]["reason"] == "path_violations"
    assert any(
        v["rule"] == "BLOCKED_CELL" for v in detail[0]["violations"]
    )


def test_422_unknown_net_index():
    body = straight_board(3)
    body["measurements"] = [rec(5, cell(0, 0, 0), cell(2, 0, 0), True)]
    detail = diagnose_422(body)["detail"]
    reasons = {(e["reason"], e.get("net")) for e in detail}
    assert ("unknown_net", 5) in reasons
    # net 0 also ends up without any usable record
    assert ("no_measurements", 0) in reasons


def test_422_negative_net_index():
    body = straight_board(3)
    body["measurements"] = [rec(-1, cell(0, 0, 0), cell(2, 0, 0), True)]
    detail = diagnose_422(body)["detail"]
    assert any(e["reason"] == "unknown_net" for e in detail)


def test_422_probe_not_on_path():
    body = straight_board(5)
    body["measurements"] = [
        rec(0, cell(0, 0, 0), cell(4, 1, 0), True),  # (4,1) not in path
    ]
    detail = diagnose_422(body)["detail"]
    bad = [e for e in detail if e["reason"] == "probe_not_on_path"]
    assert len(bad) == 1
    assert bad[0]["measurement"] == 0 and bad[0]["net"] == 0
    assert bad[0]["probe"] == "b"
    assert bad[0]["cell"] == {"x": 4, "y": 1, "layer": 0}


def test_422_probe_wrong_layer_at_same_coordinate():
    body = via_board()
    # (1,0,1) exists but (1,0,0)-straddling probe mislabelled as layer 0
    # at a coordinate that exists on both layers: here (1,1,1) is in the
    # path, (1,1,0) is not
    body["measurements"] = [
        rec(0, cell(0, 0, 0), cell(1, 1, 0), True),
    ]
    detail = diagnose_422(body)["detail"]
    bad = [e for e in detail if e["reason"] == "probe_not_on_path"]
    assert len(bad) == 1
    assert bad[0]["cell"] == {"x": 1, "y": 1, "layer": 0}


def test_422_probe_out_of_board_is_not_on_path():
    body = straight_board(5)
    body["measurements"] = [
        rec(0, cell(0, 0, 0), cell(9, 9, 0), True),
    ]
    detail = diagnose_422(body)["detail"]
    assert any(e["reason"] == "probe_not_on_path" for e in detail)


def test_422_net_without_measurement():
    body = two_net_board()
    body["measurements"] = [
        rec(0, cell(0, 0, 0), cell(4, 0, 0), True),
        # net 1 has no record
    ]
    detail = diagnose_422(body)["detail"]
    assert detail == [{"reason": "no_measurements", "net": 1,
                       "msg": "net 1 has no valid measurement record"}]


def test_422_collects_every_bad_record_at_once():
    body = two_net_board()
    body["measurements"] = [
        rec(9, cell(0, 0, 0), cell(4, 0, 0), True),         # unknown net
        rec(0, cell(0, 0, 0), cell(9, 0, 0), True),         # bad probe
    ]
    detail = diagnose_422(body)["detail"]
    assert [e["measurement"] for e in detail
            if e["reason"] != "no_measurements"] == [0, 1]


def test_422_missing_measurements_field():
    body = straight_board(3)
    assert client.post("/diagnose-open", json=body).status_code == 422


def test_422_empty_measurements_list():
    body = straight_board(3)
    body["measurements"] = []
    assert client.post("/diagnose-open", json=body).status_code == 422


def test_422_non_integer_probe_coordinate():
    body = straight_board(3)
    for bad in (
        {"x": 1.0, "y": 0, "layer": 0},
        {"x": "1", "y": 0, "layer": 0},
        {"x": True, "y": 0, "layer": 0},
        {"x": 0, "y": 0, "layer": 0.5},
    ):
        body["measurements"] = [
            {"net": 0, "a": cell(0, 0, 0), "b": bad, "connected": True}
        ]
        r = client.post("/diagnose-open", json=body)
        assert r.status_code == 422, bad


def test_422_connected_must_be_boolean():
    body = straight_board(3)
    for value in (1, 0, "true", None):
        body["measurements"] = [
            {"net": 0, "a": cell(0, 0, 0), "b": cell(2, 0, 0),
             "connected": value}
        ]
        r = client.post("/diagnose-open", json=body)
        assert r.status_code == 422, value


def test_422_board_level_validation_still_applies():
    body = straight_board(3)
    body["blocked"] = [cell(0, 0, 0)]  # pad sits on blocked cell
    body["measurements"] = [rec(0, cell(0, 0, 0), cell(2, 0, 0), True)]
    assert client.post("/diagnose-open", json=body).status_code == 422


def test_422_path_count_mismatch():
    body = two_net_board()
    body["paths"] = body["paths"][:1]
    body["measurements"] = [
        rec(0, cell(0, 0, 0), cell(4, 0, 0), True),
        rec(1, cell(0, 2, 0), cell(4, 2, 0), True),
    ]
    assert client.post("/diagnose-open", json=body).status_code == 422


# ---------------------- existing endpoints stay unchanged -------------------

def test_route_and_inspect_still_work():
    assert client.get("/health").json() == {"status": "ok"}
    body = straight_board(3)
    r = client.post("/inspect", json=body)
    assert r.status_code == 200 and r.json() == {"legal": True,
                                                 "violations": []}
    r = client.post("/route", json={
        "width": 3, "height": 3,
        "nets": [net(cell(0, 0, 0), cell(2, 0, 0))],
    })
    assert r.status_code == 200 and r.json()["status"] == "optimal"
