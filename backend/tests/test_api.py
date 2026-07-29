"""API contract tests against the real canonical.db (built by the pipeline)."""

import pytest
from fastapi.testclient import TestClient

from api.db import DB_PATH
from api.main import app

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(), reason="canonical.db not built — run `python -m pipeline.run`"
)

client = TestClient(app)


def test_health():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_stats_shape():
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert {"hotels", "hotels_by_match_method", "rooms", "near_misses", "llm_spend"} <= set(body)
    assert body["hotels"].get("matched", 0) > 0
    # Every matched hotel came from a known method (geo_fuzzy, rescue, or llm)
    assert set(body["hotels_by_match_method"]) <= {"geo_fuzzy", "rescue", "llm", "singleton"}


def test_list_hotels_pagination():
    r = client.get("/hotels", params={"limit": 5, "offset": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 5 and body["offset"] == 0
    assert len(body["hotels"]) == 5
    assert body["total"] >= 5
    assert body["has_more"] is (body["total"] > 5)
    assert all(h["match_method"] in {"geo_fuzzy", "rescue", "llm", "singleton"} for h in body["hotels"])


def test_list_hotels_has_more_false_on_last_page():
    total = client.get("/hotels", params={"limit": 1}).json()["total"]
    r = client.get("/hotels", params={"limit": 1, "offset": total - 1})
    assert r.status_code == 200
    assert r.json()["has_more"] is False


def test_search_returns_relevant_results():
    r = client.get("/hotels", params={"search": "Taj", "limit": 5})
    assert r.status_code == 200
    hotels = r.json()["hotels"]
    assert hotels, "expected results for 'Taj'"
    assert any("taj" in (h["name"] + h["address"]).lower() for h in hotels)


def test_search_special_characters_no_500():
    for q in ['St."Marks', "hotel's", "a)(b", "-", '"""']:
        r = client.get("/hotels", params={"search": q})
        assert r.status_code == 200, f"query {q!r} should not error"


def test_match_status_validation():
    assert client.get("/hotels", params={"match_status": "matched"}).status_code == 200
    # Invalid enum values must be rejected with 422, not silently ignored
    assert client.get("/hotels", params={"match_status": "banana"}).status_code == 422


def test_limit_bounds():
    assert client.get("/hotels", params={"limit": 0}).status_code == 422
    assert client.get("/hotels", params={"limit": 999}).status_code == 422


def test_hotel_detail_contract():
    hotel_id = client.get("/hotels", params={"match_status": "matched", "limit": 1}).json()["hotels"][0]["id"]
    r = client.get(f"/hotels/{hotel_id}")
    assert r.status_code == 200
    d = r.json()
    for key in ["id", "name", "address", "lat", "lon", "stars", "amenities",
                "image_urls", "match_status", "match_confidence",
                "sources", "rooms", "near_misses"]:
        assert key in d, f"missing {key}"
    # Matched hotel must carry both verbatim source records
    assert d["sources"]["supplier_a"] is not None
    assert d["sources"]["supplier_b"] is not None
    # Room contract
    for room in d["rooms"]:
        for key in ["id", "name", "bed_type", "occupancy", "meal_plan", "view",
                    "match_status", "match_confidence"]:
            assert key in room
        assert 0.0 <= room["match_confidence"] <= 1.0
    assert d["match_method"] in {"geo_fuzzy", "rescue", "llm"}
    for nm in d["near_misses"]:
        assert nm["supplier"] in ("a", "b")
        assert "supplier_id" in nm


def test_near_miss_present_for_a_singleton_hotel():
    """a_only/b_only hotels can have a live near-miss candidate — this used
    to be silently dropped for anything but a matched hotel."""
    r = client.get("/hotels", params={"match_status": "a_only", "limit": 200})
    singleton_ids = [h["id"] for h in r.json()["hotels"]]
    assert any(
        client.get(f"/hotels/{hid}").json()["near_misses"] for hid in singleton_ids
    ), "expected at least one a_only hotel with a near-miss candidate"


def test_hotel_404():
    r = client.get("/hotels/CAN-99999")
    assert r.status_code == 404


def test_request_id_header_present():
    r = client.get("/")
    assert "x-request-id" in {k.lower() for k in r.headers}
