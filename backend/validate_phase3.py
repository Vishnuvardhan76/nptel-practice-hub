"""
Phase 3 Validation Script for NPTEL Practice Hub
Validates Flask foundation endpoints (/api/health, /api/weeks), static asset serving,
security isolation (no answer keys exposed), and frontend-backend separation.
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import app
from database import get_db_connection

def run_phase3_validation():
    print("=== NPTEL Practice Hub Phase 3 Foundation Validation ===")
    results = {}

    client = app.test_client()

    # 1. Test Health Endpoint
    print("\n[1] Testing GET /api/health...")
    try:
        resp = client.get("/api/health")
        assert resp.status_code == 200, f"Expected status 200, got {resp.status_code}"
        data = json.loads(resp.data.decode("utf-8"))
        assert data.get("status") == "healthy", f"Unexpected health status: {data}"
        assert "NPTEL Practice Hub" in data.get("service", ""), f"Unexpected service: {data}"
        print(f" -> PASS: Health check succeeded: {data}")
        results["Health endpoint"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Health endpoint"] = "FAIL"

    # 2. Test Weeks Endpoint
    print("\n[2] Testing GET /api/weeks...")
    try:
        resp = client.get("/api/weeks")
        assert resp.status_code == 200, f"Expected status 200, got {resp.status_code}"
        data = json.loads(resp.data.decode("utf-8"))
        assert data.get("status") == "success", f"Unexpected status: {data}"
        assert data.get("count") == 12, f"Expected 12 weeks, got {data.get('count')}"
        weeks = data.get("weeks", [])
        assert len(weeks) == 12, f"Expected 12 weeks, got {len(weeks)}"
        for w in weeks:
            assert "week_number" in w
            assert "title" in w
            assert w.get("verified_questions") == 10
            # SECURITY CHECK: Ensure no questions, options, or answers are exposed
            assert "options" not in w, "SECURITY BREACH: options exposed in /api/weeks!"
            assert "is_correct" not in w, "SECURITY BREACH: is_correct exposed in /api/weeks!"
            assert "correct_option" not in w, "SECURITY BREACH: correct_option exposed in /api/weeks!"
            assert "answers" not in w, "SECURITY BREACH: answers exposed in /api/weeks!"
        print(f" -> PASS: /api/weeks returned 12 weeks with verified question count = 10.")
        results["Weeks endpoint"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Weeks endpoint"] = "FAIL"

    # 3. Test Security Isolation (Answer Key Protection)
    print("\n[3] Testing public API answer-key isolation...")
    try:
        resp_text = resp.data.decode("utf-8").lower()
        forbidden_keys = ["is_correct", "option_letter", "option_text", "option_order", "correct_option_id"]
        for key in forbidden_keys:
            assert key not in resp_text, f"Forbidden key '{key}' found in public /api/weeks response!"
        print(" -> PASS: Confirmed zero answer keys or option data exposed in public API.")
        results["Answer key isolation"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Answer key isolation"] = "FAIL"

    # 4. Test Frontend Static Asset Serving
    print("\n[4] Testing frontend static file serving...")
    try:
        # Check index.html
        resp_index = client.get("/")
        assert resp_index.status_code == 200, f"Index route returned {resp_index.status_code}"
        assert b"NPTEL" in resp_index.data
        assert b"Conservation Geography" in resp_index.data

        # Check CSS
        resp_css = client.get("/assets/css/style.css")
        assert resp_css.status_code == 200, f"CSS returned {resp_css.status_code}"
        assert b"#0B0F19" in resp_css.data or b"#0b0f19" in resp_css.data

        # Check JS
        resp_js = client.get("/assets/js/app.js")
        assert resp_js.status_code == 200, f"JS returned {resp_js.status_code}"
        assert b"checkHealth" in resp_js.data

        print(" -> PASS: Frontend index.html, style.css, and app.js served successfully.")
        results["Frontend static serving"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Frontend static serving"] = "FAIL"

    # 5. Database Connection and Integrity Check
    print("\n[5] Testing database connectivity through existing database.py helper...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys;")
        assert cursor.fetchone()[0] == 1, "Foreign keys are not enabled!"
        cursor.execute("SELECT COUNT(*) FROM questions WHERE is_verified = 1;")
        count = cursor.fetchone()[0]
        assert count == 120, f"Expected 120 verified questions, found {count}"
        conn.close()
        print(" -> PASS: Database connection verified; foreign keys active; 120 verified questions intact.")
        results["Database integrity"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Database integrity"] = "FAIL"

    print("\n=== Phase 3 Validation Summary ===")
    all_passed = True
    for test_name, status in results.items():
        print(f" - {test_name}: {status}")
        if status != "PASS":
            all_passed = False

    if not all_passed:
        raise SystemExit("Phase 3 validation failed!")

    print("\nAll Phase 3 validation checks PASSED successfully.")

if __name__ == "__main__":
    run_phase3_validation()
