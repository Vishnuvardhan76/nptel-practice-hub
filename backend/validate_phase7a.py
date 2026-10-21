"""
Phase 7A Validation Suite for NPTEL Practice Hub
Validates Phase 7A Security Hardening:
1. Guest attempt-history isolation (client_id requirement & isolation).
2. Session ownership validation (create, get, autosave, submit, results).
3. Legacy-session protection (client_id IS NULL never claimed or modified, returns 403).
4. Restricted CORS allowlist & preflight headers (X-Client-ID supported, wildcard rejected).
5. API 404 JSON catch-all (unmatched /api/* routes return JSON 404).
6. Client-blind practice session security (no answer leakage during test).
7. Read-only regressions (Health check, /api/weeks, Learn Mode /api/weeks/1/questions).
8. Database isolation: 100% executed in an isolated temporary SQLite database copy;
   verifies production database SHA-256 remains completely untouched.
"""

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import app
from database import DEFAULT_DB_PATH

EXPECTED_DB_SHA256 = "9df5eec74bad9543c111a2831dda57a2b58d4e16cbca57d47ccc767a33ad34d1"


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def run_phase7a_validation():
    print("=" * 70)
    print("NPTEL Practice Hub — Phase 7A Security Hardening Validation Suite")
    print("=" * 70)

    # 1. Verify production DB integrity before test run
    print("\n[Step 0] Verifying production database pre-test integrity...")
    initial_hash = compute_sha256(DEFAULT_DB_PATH)
    assert initial_hash == EXPECTED_DB_SHA256, (
        f"Production database hash mismatch!\nExpected: {EXPECTED_DB_SHA256}\nFound:    {initial_hash}"
    )
    print(f" -> PASS: Production database hash verified: {initial_hash}")

    # 2. Setup isolated temporary database copy
    print("\n[Step 0.1] Provisioning isolated temporary database environment...")
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    temp_db_path = Path(temp_dir.name) / "isolated_test_hub.db"
    shutil.copy2(DEFAULT_DB_PATH, temp_db_path)

    # Configure Flask app to use isolated database
    app.config["DATABASE_PATH"] = str(temp_db_path)
    client = app.test_client()
    print(f" -> PASS: Isolated test database active at: {temp_db_path}")

    results = {}

    # Test Client IDs
    guest_a = str(uuid.uuid4())
    guest_b = str(uuid.uuid4())
    malformed_id_short = "abc"
    malformed_id_chars = "client-with-illegal-chars-!@#$"
    malformed_id_long = "a" * 80

    try:
        # ---------------------------------------------------------------------
        # TEST 1: Attempt History Security (GET /api/practice/attempts)
        # ---------------------------------------------------------------------
        print("\n[Test 1] Testing Attempt History Security & Client Isolation...")

        # 1.1 Missing client_id returns 400
        r = client.get("/api/practice/attempts")
        assert r.status_code == 400, f"Expected 400 for missing client_id, got {r.status_code}"
        d = r.get_json()
        assert d["status"] == "error"
        assert "client_id is required" in d["message"].lower()
        print(" -> PASS: Missing client_id rejected with HTTP 400.")

        # 1.2 Malformed client_id returns 400
        for bad_id in [malformed_id_short, malformed_id_chars, malformed_id_long]:
            r = client.get(f"/api/practice/attempts?client_id={bad_id}")
            assert r.status_code == 400, f"Expected 400 for bad client_id '{bad_id}', got {r.status_code}"
            d = r.get_json()
            assert "invalid client_id format" in d["message"].lower()
        print(" -> PASS: Malformed client_id formats rejected with HTTP 400.")

        # 1.3 Empty history for new guest
        r = client.get(f"/api/practice/attempts?client_id={guest_a}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        d = r.get_json()
        assert d["count"] == 0
        assert len(d["attempts"]) == 0
        print(" -> PASS: New guest returns empty attempt history.")

        # 1.4 Create & submit a session for Guest A, verify isolation from Guest B
        res_create = client.post("/api/practice/sessions",
            headers={"X-Client-ID": guest_a},
            json={"weeks": [1], "test_type": "quick", "question_count": 10}
        )
        assert res_create.status_code == 201, f"Expected 201, got {res_create.status_code}: {res_create.data}"
        session_a_id = res_create.get_json()["session"]["session_id"]

        # Submit session for Guest A
        res_sub = client.post(f"/api/practice/sessions/{session_a_id}/submit",
            headers={"X-Client-ID": guest_a},
            json={"answers": {}}
        )
        assert res_sub.status_code == 200, f"Expected 200, got {res_sub.status_code}"

        # Guest A query -> sees 1 attempt
        r_a = client.get("/api/practice/attempts", headers={"X-Client-ID": guest_a})
        assert r_a.status_code == 200
        d_a = r_a.get_json()
        assert d_a["count"] == 1
        assert d_a["attempts"][0]["session_id"] == session_a_id

        # Guest B query -> sees 0 attempts (STRICT ISOLATION)
        r_b = client.get("/api/practice/attempts", headers={"X-Client-ID": guest_b})
        assert r_b.status_code == 200
        d_b = r_b.get_json()
        assert d_b["count"] == 0, f"SECURITY LEAK: Guest B saw {d_b['count']} attempts!"
        print(" -> PASS: Complete attempt history isolation between Guest A and Guest B.")
        results["1. Attempt History Isolation"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 2: Session Creation Ownership
        # ---------------------------------------------------------------------
        print("\n[Test 2] Testing Session Creation Ownership Validation...")

        # 2.1 Creation without client_id -> 400
        r_no_id = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "quick", "question_count": 10})
        assert r_no_id.status_code == 400
        assert "client_id is required" in r_no_id.get_json()["message"].lower()
        print(" -> PASS: Session creation rejected without client ID.")

        # 2.2 Creation with malformed client_id -> 400
        r_bad_id = client.post("/api/practice/sessions",
            headers={"X-Client-ID": malformed_id_chars},
            json={"weeks": [1], "test_type": "quick", "question_count": 10}
        )
        assert r_bad_id.status_code == 400, f"Expected 400, got {r_bad_id.status_code}: {r_bad_id.data}"
        assert "client_id is required" in r_bad_id.get_json()["message"].lower()
        print(" -> PASS: Session creation rejected with invalid client ID format.")

        # 2.3 Creation with valid client_id -> 201 & stores in DB
        r_ok = client.post("/api/practice/sessions",
            headers={"X-Client-ID": guest_b},
            json={"weeks": [1, 2], "test_type": "quick", "question_count": 10}
        )
        assert r_ok.status_code == 201
        session_b_data = r_ok.get_json()["session"]
        session_b_id = session_b_data["session_id"]
        sample_q_id = session_b_data["questions"][0]["id"]
        sample_opt_id = session_b_data["questions"][0]["options"][0]["id"]

        # Check DB column in isolated db
        with sqlite3.connect(str(temp_db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT client_id FROM practice_sessions WHERE session_id = ?", (session_b_id,)).fetchone()
            assert row is not None
            assert row["client_id"] == guest_b, f"Expected {guest_b}, got {row['client_id']}"
        print(" -> PASS: Valid session creation stores verified client_id.")
        results["2. Session Creation Ownership"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 3: Active Session Retrieval Ownership (GET /api/practice/sessions/<id>)
        # ---------------------------------------------------------------------
        print("\n[Test 3] Testing Active Session Retrieval Ownership...")

        # 3.1 Owner retrieval -> 200
        r_own = client.get(f"/api/practice/sessions/{session_b_id}", headers={"X-Client-ID": guest_b})
        assert r_own.status_code == 200
        assert r_own.get_json()["session"]["session_id"] == session_b_id
        print(" -> PASS: Owner successfully retrieves session.")

        # 3.2 Unauthenticated retrieval (no header) -> 401
        r_unauth = client.get(f"/api/practice/sessions/{session_b_id}")
        assert r_unauth.status_code == 401, f"Expected 401, got {r_unauth.status_code}"
        print(" -> PASS: Missing client ID returns HTTP 401.")

        # 3.3 Mismatched client retrieval (Guest A tries to access Guest B's session) -> 403
        r_mismatch = client.get(f"/api/practice/sessions/{session_b_id}", headers={"X-Client-ID": guest_a})
        assert r_mismatch.status_code == 403, f"Expected 403, got {r_mismatch.status_code}"
        assert "Access denied" in r_mismatch.get_json()["message"]
        print(" -> PASS: Mismatched client ID returns HTTP 403 Access Denied.")

        # 3.4 Nonexistent session -> 404
        r_nonexist = client.get(f"/api/practice/sessions/{uuid.uuid4()}", headers={"X-Client-ID": guest_a})
        assert r_nonexist.status_code == 404
        print(" -> PASS: Nonexistent session returns HTTP 404.")
        results["3. Session Retrieval Ownership"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 4: Answer Autosaving Ownership (PUT /api/practice/sessions/<id>/answers)
        # ---------------------------------------------------------------------
        print("\n[Test 4] Testing Answer Autosaving Ownership...")

        # 4.1 Missing client ID -> 401
        r_save_unauth = client.post(f"/api/practice/sessions/{session_b_id}/answers", json={"answers": {str(sample_q_id): sample_opt_id}})
        assert r_save_unauth.status_code == 401, f"Expected 401, got {r_save_unauth.status_code}: {r_save_unauth.data}"
        print(" -> PASS: Unauthenticated autosave returns HTTP 401.")

        # 4.2 Mismatched client ID (Guest A tries to answer Guest B's session) -> 403
        r_save_mismatch = client.post(f"/api/practice/sessions/{session_b_id}/answers",
            headers={"X-Client-ID": guest_a},
            json={"answers": {str(sample_q_id): sample_opt_id}}
        )
        assert r_save_mismatch.status_code == 403
        print(" -> PASS: Mismatched autosave returns HTTP 403.")

        # 4.3 Owner autosave -> 200
        r_save_owner = client.post(f"/api/practice/sessions/{session_b_id}/answers",
            headers={"X-Client-ID": guest_b},
            json={"answers": {str(sample_q_id): sample_opt_id}}
        )
        assert r_save_owner.status_code == 200, f"Expected 200, got {r_save_owner.status_code}: {r_save_owner.data}"
        print(" -> PASS: Owner autosave succeeds with HTTP 200.")
        results["4. Answer Autosave Ownership"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 5: Test Submission Ownership & Submission Lock
        # ---------------------------------------------------------------------
        print("\n[Test 5] Testing Test Submission Ownership & Lock...")

        # 5.1 Missing client ID -> 401
        r_sub_unauth = client.post(f"/api/practice/sessions/{session_b_id}/submit", json={"answers": {}})
        assert r_sub_unauth.status_code == 401
        print(" -> PASS: Unauthenticated submission returns HTTP 401.")

        # 5.2 Mismatched client ID -> 403
        r_sub_mismatch = client.post(f"/api/practice/sessions/{session_b_id}/submit",
            headers={"X-Client-ID": guest_a},
            json={"answers": {}}
        )
        assert r_sub_mismatch.status_code == 403
        print(" -> PASS: Mismatched submission returns HTTP 403.")

        # 5.3 Owner submission -> 200
        r_sub_owner = client.post(f"/api/practice/sessions/{session_b_id}/submit",
            headers={"X-Client-ID": guest_b},
            json={"answers": {str(sample_q_id): sample_opt_id}}
        )
        assert r_sub_owner.status_code == 200, f"Expected 200, got {r_sub_owner.status_code}: {r_sub_owner.data}"
        d_sub = r_sub_owner.get_json()
        assert d_sub.get("status") in ["success", "submitted"], f"d_sub: {d_sub}"
        assert "score" in d_sub
        print(" -> PASS: Owner submission succeeds with HTTP 200.")

        # 5.4 Re-submission / answer save on submitted test -> 403
        r_re_save = client.post(f"/api/practice/sessions/{session_b_id}/answers",
            headers={"X-Client-ID": guest_b},
            json={"answers": {str(sample_q_id): sample_opt_id}}
        )
        assert r_re_save.status_code == 403
        assert "submitted" in r_re_save.get_json()["message"].lower()
        print(" -> PASS: Modification after submission rejected with HTTP 403.")
        results["5. Submission Ownership & Lock"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 6: Results Review Ownership (GET /api/practice/sessions/<id>/results)
        # ---------------------------------------------------------------------
        print("\n[Test 6] Testing Results Review Ownership...")

        # 6.1 Missing client ID -> 401
        r_res_unauth = client.get(f"/api/practice/sessions/{session_b_id}/results")
        assert r_res_unauth.status_code == 401
        print(" -> PASS: Unauthenticated results review returns HTTP 401.")

        # 6.2 Mismatched client ID (Guest A requests Guest B's results) -> 403
        r_res_mismatch = client.get(f"/api/practice/sessions/{session_b_id}/results", headers={"X-Client-ID": guest_a})
        assert r_res_mismatch.status_code == 403
        print(" -> PASS: Mismatched results review returns HTTP 403.")

        # 6.3 Owner results review -> 200
        r_res_owner = client.get(f"/api/practice/sessions/{session_b_id}/results", headers={"X-Client-ID": guest_b})
        assert r_res_owner.status_code == 200, f"Expected 200, got {r_res_owner.status_code}: {r_res_owner.data}"
        d_res = r_res_owner.get_json()
        assert d_res["status"] == "success"
        assert d_res["session_id"] == session_b_id
        assert len(d_res["questions"]) > 0
        print(" -> PASS: Owner results review succeeds with HTTP 200.")
        results["6. Results Review Ownership"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 7: Mandatory Legacy-Session Protection
        # ---------------------------------------------------------------------
        print("\n[Test 7] Testing Mandatory Legacy-Session Protection...")

        # Locate an existing legacy unowned session in the isolated DB
        with sqlite3.connect(str(temp_db_path)) as conn:
            conn.row_factory = sqlite3.Row
            legacy_row = conn.execute(
                "SELECT session_id, client_id FROM practice_sessions WHERE client_id IS NULL LIMIT 1"
            ).fetchone()
            assert legacy_row is not None, "Expected legacy session with client_id IS NULL in test DB!"
            legacy_session_id = legacy_row["session_id"]
            print(f" -> Found legacy unowned session: {legacy_session_id}")

        # 7.1 Any client trying to access legacy session -> 403
        r_leg_get = client.get(f"/api/practice/sessions/{legacy_session_id}", headers={"X-Client-ID": guest_a})
        assert r_leg_get.status_code == 403, f"Expected 403, got {r_leg_get.status_code}"
        assert "legacy unowned session" in r_leg_get.get_json()["message"]
        print(" -> PASS: Legacy session retrieval denied with HTTP 403.")

        # 7.2 Any client trying to autosave legacy session -> 403
        r_leg_put = client.put(f"/api/practice/sessions/{legacy_session_id}/answers",
            headers={"X-Client-ID": guest_a},
            json={"answers": {}}
        )
        assert r_leg_put.status_code == 403
        print(" -> PASS: Legacy session autosave denied with HTTP 403.")

        # 7.3 Any client trying to submit legacy session -> 403
        r_leg_sub = client.post(f"/api/practice/sessions/{legacy_session_id}/submit",
            headers={"X-Client-ID": guest_a},
            json={"answers": {}}
        )
        assert r_leg_sub.status_code == 403
        print(" -> PASS: Legacy session submission denied with HTTP 403.")

        # 7.4 Any client trying to get legacy session results -> 403
        r_leg_res = client.get(f"/api/practice/sessions/{legacy_session_id}/results", headers={"X-Client-ID": guest_a})
        assert r_leg_res.status_code == 403
        print(" -> PASS: Legacy session results denied with HTTP 403.")

        # 7.5 Verify in DB: Legacy record client_id MUST STILL BE NULL! (Never silently claimed)
        with sqlite3.connect(str(temp_db_path)) as conn:
            conn.row_factory = sqlite3.Row
            check_row = conn.execute(
                "SELECT client_id FROM practice_sessions WHERE session_id = ?", (legacy_session_id,)
            ).fetchone()
            assert check_row["client_id"] is None, f"SECURITY BREACH: Legacy record was claimed: {check_row['client_id']}"
        print(" -> PASS: Legacy record client_id remains strictly NULL in database.")
        results["7. Legacy-Session Protection"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 8: CORS Origin Allowlist & Preflight Headers
        # ---------------------------------------------------------------------
        print("\n[Test 8] Testing CORS Origin Restrictions & Preflights...")

        # 8.1 Allowed origins
        for allowed in ["http://127.0.0.1:5500", "http://localhost:3000", "null"]:
            res_cors = client.get("/api/health", headers={"Origin": allowed})
            assert res_cors.headers.get("Access-Control-Allow-Origin") == allowed, (
                f"Expected Allow-Origin {allowed}, got {res_cors.headers.get('Access-Control-Allow-Origin')}"
            )
            assert "Origin" in res_cors.headers.get("Vary", "")

        # 8.2 Disallowed origins (e.g. evil.com)
        res_evil = client.get("/api/health", headers={"Origin": "http://evil-attacker.com"})
        assert "Access-Control-Allow-Origin" not in res_evil.headers
        print(" -> PASS: Allowed origins reflected with Vary: Origin; disallowed origins rejected.")

        # 8.3 Preflight OPTIONS with X-Client-ID
        res_preflight = client.options("/api/practice/sessions",
            headers={
                "Origin": "http://127.0.0.1:5500",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-Client-ID, Content-Type"
            }
        )
        assert res_preflight.status_code == 200
        allow_headers = res_preflight.headers.get("Access-Control-Allow-Headers", "")
        assert "X-Client-ID" in allow_headers
        assert "Content-Type" in allow_headers
        print(" -> PASS: CORS preflight allows X-Client-ID and Content-Type.")
        results["8. CORS Allowlist & Preflight"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 9: Unknown API Catch-All (JSON 404)
        # ---------------------------------------------------------------------
        print("\n[Test 9] Testing Unknown /api/* Route JSON 404 Catch-All...")

        r_404_get = client.get("/api/nonexistent_route_test")
        assert r_404_get.status_code == 404
        assert r_404_get.content_type.startswith("application/json")
        d_404 = r_404_get.get_json()
        assert d_404["status"] == "error"
        assert "not found" in d_404["message"].lower()

        r_404_post = client.post("/api/another/missing/endpoint")
        assert r_404_post.status_code == 404
        assert r_404_post.content_type.startswith("application/json")
        print(" -> PASS: Unknown /api/* endpoints return clean JSON 404.")
        results["9. API JSON 404 Catch-All"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 10: Client-Blind Active Test Security
        # ---------------------------------------------------------------------
        print("\n[Test 10] Testing Client-Blind Security on Active Sessions...")

        r_active = client.post("/api/practice/sessions",
            headers={"X-Client-ID": guest_a},
            json={"weeks": [1], "test_type": "quick", "question_count": 10}
        )
        assert r_active.status_code == 201
        session_data = r_active.get_json()["session"]
        for q in session_data["questions"]:
            assert "is_correct" not in q
            assert "correct_option" not in q
            assert "explanation" not in q
            for opt in q["options"]:
                assert "is_correct" not in opt
                assert "is_answer" not in opt
        print(" -> PASS: Active practice test strictly conceals answers and explanations.")
        results["10. Client-Blind Question Security"] = "PASS"

        # ---------------------------------------------------------------------
        # TEST 11: Read-Only Regressions (Health, Weeks, Learn Mode)
        # ---------------------------------------------------------------------
        print("\n[Test 11] Testing Read-Only Regressions (Health, Weeks, Learn Mode)...")

        # Health
        r_h = client.get("/api/health")
        assert r_h.status_code == 200
        assert r_h.get_json()["status"] == "healthy"

        # Weeks
        r_w = client.get("/api/weeks")
        assert r_w.status_code == 200
        assert r_w.get_json()["count"] == 12

        # Learn Mode questions
        r_lm = client.get("/api/weeks/1/questions")
        assert r_lm.status_code == 200
        lm_data = r_lm.get_json()
        assert lm_data["total_questions"] == 10
        # Learn Mode legitimately contains explanations and correct answers
        assert len(lm_data["questions"]) == 10
        print(" -> PASS: Health, /api/weeks, and Learn Mode /api/weeks/1/questions work without regressions.")
        results["11. Prior Phase Regressions"] = "PASS"

    finally:
        # Reset app config
        app.config["DATABASE_PATH"] = None
        # Clean up temp directory
        temp_dir.cleanup()
        print("\n[Step Cleanup] Isolated test directory destroyed.")

    # 12. Verify production DB was NEVER touched during the entire test suite!
    print("\n[Step 12] Verifying production database post-test integrity...")
    post_hash = compute_sha256(DEFAULT_DB_PATH)
    assert post_hash == initial_hash, (
        f"CRITICAL SAFETY VIOLATION: Production database was modified during testing!\n"
        f"Initial: {initial_hash}\nPost-test: {post_hash}"
    )
    print(f" -> PASS: Production database hash UNCHANGED: {post_hash}")
    results["12. Production DB Safety"] = "PASS"

    print("\n" + "=" * 70)
    print("PHASE 7A VALIDATION SUMMARY:")
    all_passed = True
    for test_name, status in results.items():
        print(f"  {test_name.ljust(40)}: {status}")
        if status != "PASS":
            all_passed = False
    print("=" * 70)

    if not all_passed:
        raise SystemExit("Phase 7A validation failed!")
    print("ALL PHASE 7A SECURITY VALIDATIONS PASSED SUCCESSFULLY!\n")


if __name__ == "__main__":
    run_phase7a_validation()
