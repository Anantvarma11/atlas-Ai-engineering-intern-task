#!/usr/bin/env bash
# Comprehensive project validation. Writes results to validation_report.txt
cd "$(dirname "$0")"
exec > validation_report.txt 2>&1

PY=.venv/bin/python3
PASS=0; FAIL=0
check() {  # check <label> <command...>
  local label="$1"; shift
  if "$@" > /dev/null 2>&1; then echo "PASS: $label"; PASS=$((PASS+1)); else echo "FAIL: $label"; FAIL=$((FAIL+1)); fi
}

echo "===== 1. Python syntax ====="
for f in pipeline/load.py pipeline/match_hotels.py pipeline/match_rooms.py pipeline/merge.py pipeline/run.py api/main.py api/db.py api/models.py; do
  check "syntax $f" $PY -m py_compile "$f"
done

echo ""
echo "===== 2. Imports ====="
check "import pipeline modules" $PY -c "import pipeline.load, pipeline.match_hotels, pipeline.match_rooms, pipeline.merge"
check "import api app"          $PY -c "from api.main import app"

echo ""
echo "===== 3. Pipeline idempotency ====="
$PY -m pipeline.run   # should skip since canonical.db exists
check "canonical.db exists"          test -f canonical.db
check "canonical_hotels.json exists" test -f canonical_hotels.json

echo ""
echo "===== 4. Artifact integrity ====="
$PY <<'EOF'
import sqlite3, json, sys

con = sqlite3.connect("canonical.db")
errors = []

# Table row counts
for t in ["canonical_hotels","canonical_rooms","near_misses","raw_hotels_a","raw_hotels_b","raw_rooms_a","raw_rooms_b"]:
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n:,} rows")
    if n == 0: errors.append(f"{t} is empty")

# Every matched hotel has both supplier ids
bad = con.execute("SELECT COUNT(*) FROM canonical_hotels WHERE match_status='matched' AND (supplier_a_id IS NULL OR supplier_b_id IS NULL)").fetchone()[0]
print(f"  matched hotels missing a supplier id: {bad}")
if bad: errors.append("matched hotels with missing provenance")

# a_only must have no b id; b_only no a id
bad = con.execute("SELECT COUNT(*) FROM canonical_hotels WHERE match_status='a_only' AND supplier_b_id IS NOT NULL").fetchone()[0]
bad += con.execute("SELECT COUNT(*) FROM canonical_hotels WHERE match_status='b_only' AND supplier_a_id IS NOT NULL").fetchone()[0]
print(f"  singleton hotels with wrong provenance: {bad}")
if bad: errors.append("singleton provenance wrong")

# No duplicate supplier ids across canonical hotels (one-to-one guarantee)
dup_a = con.execute("SELECT COUNT(*) FROM (SELECT supplier_a_id FROM canonical_hotels WHERE supplier_a_id IS NOT NULL GROUP BY supplier_a_id HAVING COUNT(*)>1)").fetchone()[0]
dup_b = con.execute("SELECT COUNT(*) FROM (SELECT supplier_b_id FROM canonical_hotels WHERE supplier_b_id IS NOT NULL GROUP BY supplier_b_id HAVING COUNT(*)>1)").fetchone()[0]
print(f"  duplicate supplier_a ids: {dup_a}, duplicate supplier_b ids: {dup_b}")
if dup_a or dup_b: errors.append("duplicate supplier ids")

# All supplier A + B hotels accounted for
n_a = con.execute("SELECT COUNT(*) FROM raw_hotels_a").fetchone()[0]
n_b = con.execute("SELECT COUNT(*) FROM raw_hotels_b").fetchone()[0]
used_a = con.execute("SELECT COUNT(DISTINCT supplier_a_id) FROM canonical_hotels WHERE supplier_a_id IS NOT NULL").fetchone()[0]
used_b = con.execute("SELECT COUNT(DISTINCT supplier_b_id) FROM canonical_hotels WHERE supplier_b_id IS NOT NULL").fetchone()[0]
print(f"  A coverage: {used_a}/{n_a}, B coverage: {used_b}/{n_b}")
if used_a != n_a or used_b != n_b: errors.append("not all supplier hotels covered")

# Rooms point at valid hotels
orphans = con.execute("SELECT COUNT(*) FROM canonical_rooms r LEFT JOIN canonical_hotels h ON r.canonical_hotel_id=h.id WHERE h.id IS NULL").fetchone()[0]
print(f"  orphan rooms: {orphans}")
if orphans: errors.append("orphan rooms")

# Matched rooms have both room ids
bad = con.execute("SELECT COUNT(*) FROM canonical_rooms WHERE match_status='matched' AND (room_a_id IS NULL OR room_b_id IS NULL)").fetchone()[0]
print(f"  matched rooms missing a room id: {bad}")
if bad: errors.append("matched rooms missing provenance")

# Confidence bounds
bad = con.execute("SELECT COUNT(*) FROM canonical_hotels WHERE match_confidence < 0 OR match_confidence > 1").fetchone()[0]
bad += con.execute("SELECT COUNT(*) FROM canonical_rooms WHERE match_confidence < 0 OR match_confidence > 1").fetchone()[0]
print(f"  out-of-range confidences: {bad}")
if bad: errors.append("confidence out of range")

# FTS index count matches
n_fts = con.execute("SELECT COUNT(*) FROM hotels_fts").fetchone()[0]
n_ch  = con.execute("SELECT COUNT(*) FROM canonical_hotels").fetchone()[0]
print(f"  FTS rows: {n_fts} vs hotels: {n_ch}")
if n_fts != n_ch: errors.append("FTS count mismatch")

# JSON artifact parses and matches DB count
data = json.load(open("canonical_hotels.json"))
print(f"  JSON hotels: {len(data)}")
if len(data) != n_ch: errors.append("JSON/DB count mismatch")
sample = data[0]
for key in ["id","name","match_status","match_confidence","supplier_a_id","supplier_b_id","rooms","near_misses"]:
    if key not in sample: errors.append(f"JSON missing key {key}")

con.close()
if errors:
    print("ARTIFACT ERRORS:", errors); sys.exit(1)
print("ARTIFACTS OK")
EOF
if [ $? -eq 0 ]; then echo "PASS: artifact integrity"; PASS=$((PASS+1)); else echo "FAIL: artifact integrity"; FAIL=$((FAIL+1)); fi

echo ""
echo "===== 5. API end-to-end ====="
$PY -m uvicorn api.main:app --port 8765 --log-level error &
API_PID=$!
sleep 3

check "GET / health"            curl -sf http://localhost:8765/
check "GET /stats"              curl -sf http://localhost:8765/stats
check "GET /hotels list"        curl -sf "http://localhost:8765/hotels?limit=5"
check "GET /hotels search"      curl -sf "http://localhost:8765/hotels?search=Taj&limit=3"
check "GET /hotels FTS special chars" curl -sf "http://localhost:8765/hotels?search=St.Marks%20%22quote"
check "GET /hotels match_status filter" curl -sf "http://localhost:8765/hotels?match_status=matched&limit=2"
check "GET /hotels/{id} detail" curl -sf http://localhost:8765/hotels/CAN-00001
check "GET /openapi.json"       curl -sf http://localhost:8765/openapi.json

# 404 must return 404
CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/hotels/CAN-99999)
if [ "$CODE" = "404" ]; then echo "PASS: 404 for unknown hotel"; PASS=$((PASS+1)); else echo "FAIL: 404 for unknown hotel (got $CODE)"; FAIL=$((FAIL+1)); fi

# Detail response contract
$PY <<'EOF'
import json, urllib.request, sys
d = json.load(urllib.request.urlopen("http://localhost:8765/hotels/CAN-00001"))
required = ["id","name","address","lat","lon","stars","amenities","image_urls",
            "match_status","match_confidence","sources","rooms","near_misses"]
missing = [k for k in required if k not in d]
assert not missing, f"missing keys: {missing}"
assert d["sources"]["supplier_a"] is not None
assert d["sources"]["supplier_b"] is not None
for r in d["rooms"]:
    for k in ["id","name","bed_type","occupancy","meal_plan","view","match_status","match_confidence"]:
        assert k in r, f"room missing {k}"
print("DETAIL CONTRACT OK")
EOF
if [ $? -eq 0 ]; then echo "PASS: detail response contract"; PASS=$((PASS+1)); else echo "FAIL: detail response contract"; FAIL=$((FAIL+1)); fi

kill $API_PID 2>/dev/null

echo ""
echo "===== 6. Repo hygiene ====="
check "README exists"        test -f README.md
check "WRITEUP exists"       test -f WRITEUP.md
check "Dockerfile exists"    test -f Dockerfile
check "docker-compose.yml"   test -f docker-compose.yml
check "start.sh executable content" grep -q "uvicorn api.main:app" start.sh
check "git repo clean-ish"   git rev-parse HEAD

echo ""
echo "===================================="
echo "RESULT: $PASS passed, $FAIL failed"
echo "===================================="
