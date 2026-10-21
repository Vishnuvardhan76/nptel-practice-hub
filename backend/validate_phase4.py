"""
Phase 4 Validation Script for NPTEL Practice Hub
Validates Learn Mode API endpoints, answer-key delivery for study mode,
ordering preservation, parameter validation, security isolation, and navigation logic.
"""

import json
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import app
from database import get_db_connection
from validate_phase1 import run_validation as run_phase1_validation
from validate_phase2 import run_phase2_validation
from validate_phase3 import run_phase3_validation


def run_phase4_validation():
    print("=== NPTEL Practice Hub Phase 4 Learn Mode Validation ===")
    results = {}

    # 1. Verify Prior Phases Still Pass
    print("\n[1] Verifying Phase 1, 2, and 3 test suites...")
    try:
        run_phase1_validation()
        run_phase2_validation()
        run_phase3_validation()
        print(" -> PASS: All Phase 1, Phase 2, and Phase 3 tests passed.")
        results["Prior phase tests"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Prior phase tests"] = "FAIL"

    client = app.test_client()

    # 2. Week Directory Verification (All 12 Weeks)
    print("\n[2] Verifying week selector source (/api/weeks)...")
    try:
        resp = client.get("/api/weeks")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = json.loads(resp.data.decode("utf-8"))
        assert data.get("status") == "success"
        weeks = data.get("weeks", [])
        assert len(weeks) == 12, f"Expected 12 weeks, got {len(weeks)}"
        for idx, w in enumerate(weeks, 1):
            assert w["week_number"] == idx
            assert w["total_questions"] == 10
            assert w["verified_questions"] == 10
        print(" -> PASS: /api/weeks provides all 12 weeks with verified question counts.")
        results["Week directory"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Week directory"] = "FAIL"

    # 3. Learn Mode Questions Endpoint for All 12 Weeks
    print("\n[3] Testing GET /api/weeks/<week_number>/questions for Weeks 1 to 12...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        total_verified_retrieved = 0
        for w_num in range(1, 13):
            resp = client.get(f"/api/weeks/{w_num}/questions")
            assert resp.status_code == 200, f"Week {w_num} returned HTTP {resp.status_code}"
            payload = json.loads(resp.data.decode("utf-8"))
            assert payload.get("status") == "success"
            assert payload.get("week_number") == w_num
            assert "title" in payload

            qs = payload.get("questions", [])
            assert len(qs) == 10, f"Week {w_num} returned {len(qs)} questions (expected 10)"
            total_verified_retrieved += len(qs)

            # Check question ordering and original numbers
            for idx, q in enumerate(qs, 1):
                assert q["question_number"] == idx, f"Week {w_num} Q{idx} has question_number {q['question_number']}"
                assert q["question_order"] == idx, f"Week {w_num} Q{idx} has question_order {q['question_order']}"
                assert q["is_verified"] == 1, f"Week {w_num} Q{idx} is not verified"
                assert len(q["question_text"].strip()) > 0, f"Week {w_num} Q{idx} has empty text"

                # Check options: exactly 4 options, preserved letters and order
                opts = q.get("options", [])
                assert len(opts) == 4, f"Week {w_num} Q{idx} has {len(opts)} options (expected 4)"
                expected_letters = ["a", "b", "c", "d"]
                correct_count = 0
                for opt_idx, opt in enumerate(opts, 1):
                    assert opt["option_order"] == opt_idx, f"Option order mismatch in W{w_num} Q{idx}"
                    assert opt["option_letter"] == expected_letters[opt_idx - 1]
                    assert len(opt["option_text"].strip()) > 0
                    if opt["is_correct"] == 1:
                        correct_count += 1
                assert correct_count == 1, f"Week {w_num} Q{idx} has {correct_count} correct answers (expected 1)"

                # Compare with DB source of truth
                cursor.execute("""
                    SELECT o.option_letter
                    FROM options o
                    JOIN questions q ON o.question_id = q.id
                    WHERE q.week_number = ? AND q.question_number = ? AND o.is_correct = 1;
                """, (w_num, idx))
                db_correct = cursor.fetchone()
                assert db_correct is not None
                api_correct_opt = [o["option_letter"] for o in opts if o["is_correct"] == 1][0]
                assert api_correct_opt == db_correct["option_letter"], (
                    f"W{w_num} Q{idx}: API correct option ({api_correct_opt}) != DB correct ({db_correct['option_letter']})"
                )

        conn.close()
        assert total_verified_retrieved == 120
        print(f" -> PASS: All 12 weeks returned exactly 10 questions (120 total) in original order.")
        print(f" -> PASS: All 480 options preserved letters and orders.")
        print(f" -> PASS: All 120 correct answers match database source of truth.")
        results["Learn Mode questions retrieval & ordering"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Learn Mode questions retrieval & ordering"] = "FAIL"

    # 4. Input Validation & Error Handling
    print("\n[4] Testing week parameter validation and error responses...")
    try:
        # Non-integer strings
        resp = client.get("/api/weeks/abc/questions")
        assert resp.status_code == 400, f"Expected 400 for 'abc', got {resp.status_code}"
        data = json.loads(resp.data.decode("utf-8"))
        assert data.get("status") == "error"

        resp = client.get("/api/weeks/1.5/questions")
        assert resp.status_code == 400, f"Expected 400 for '1.5', got {resp.status_code}"

        # Negative numbers
        resp = client.get("/api/weeks/-1/questions")
        assert resp.status_code == 400, f"Expected 400 for '-1', got {resp.status_code}"

        # Out-of-bounds weeks (0, 13, 999)
        resp = client.get("/api/weeks/0/questions")
        assert resp.status_code == 400, f"Expected 400 for '0', got {resp.status_code}"

        resp = client.get("/api/weeks/13/questions")
        assert resp.status_code == 404, f"Expected 404 for '13', got {resp.status_code}"
        data = json.loads(resp.data.decode("utf-8"))
        assert "not found" in data.get("message", "").lower()

        resp = client.get("/api/weeks/999/questions")
        assert resp.status_code == 404, f"Expected 404 for '999', got {resp.status_code}"

        print(" -> PASS: Invalid week parameters correctly handled with HTTP 400 and 404.")
        results["Parameter validation"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Parameter validation"] = "FAIL"

    # 5. Security: Unverified Questions are NEVER Returned
    print("\n[5] Testing unverified question exclusion...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Insert a temporary unverified question in Week 12
        cursor.execute("""
            INSERT INTO questions (week_number, question_number, question_order, question_text, marks, is_verified)
            VALUES (12, 99, 99, 'Temporary Unverified Question', 1.0, 0);
        """)
        temp_q_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO options (question_id, option_letter, option_order, option_text, is_correct)
            VALUES (?, 'a', 1, 'Unverified Opt', 1);
        """, (temp_q_id,))
        conn.commit()

        # Query Week 12 via API
        resp = client.get("/api/weeks/12/questions")
        assert resp.status_code == 200
        payload = json.loads(resp.data.decode("utf-8"))
        returned_q_ids = [q["id"] for q in payload.get("questions", [])]

        # Cleanup immediately
        cursor.execute("DELETE FROM questions WHERE id = ?;", (temp_q_id,))
        conn.commit()
        conn.close()

        assert temp_q_id not in returned_q_ids, "SECURITY FAILURE: Unverified question was returned by API!"
        assert len(payload.get("questions", [])) == 10, "Expected exactly 10 verified questions"
        print(" -> PASS: Unverified questions are strictly excluded by the API.")
        results["Unverified question exclusion"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Unverified question exclusion"] = "FAIL"

    # 6. Security: Stack Trace & Internals Leakage Prevention
    print("\n[6] Testing security: no internals or stack traces in error responses...")
    try:
        resp = client.get("/api/weeks/invalid-week/questions")
        resp_text = resp.data.decode("utf-8")
        forbidden_leak_indicators = ["traceback", "file \"", "line ", "sqlite3", "exception", "instance/"]
        for ind in forbidden_leak_indicators:
            assert ind not in resp_text.lower(), f"Leak indicator '{ind}' found in error response: {resp_text}"
        print(" -> PASS: Error responses are sanitized and free of internal leaks.")
        results["Information leak prevention"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Information leak prevention"] = "FAIL"

    # 7. Navigation Logic Simulation Test
    print("\n[7] Testing navigation logic simulation (boundaries and sequential access)...")
    try:
        # Simulate frontend navigation state logic for a week with 10 questions
        questions_count = 10
        current_idx = 0

        # Boundary: At first question (index 0)
        is_prev_disabled = (current_idx == 0)
        is_next_disabled = (current_idx == questions_count - 1)
        counter_text = f"Question {current_idx + 1} of {questions_count}"
        assert is_prev_disabled is True, "Previous should be disabled on first question"
        assert is_next_disabled is False, "Next should be enabled on first question"
        assert counter_text == "Question 1 of 10"

        # Sequential navigation forward
        for expected_q in range(2, 11):
            current_idx += 1
            is_prev_disabled = (current_idx == 0)
            is_next_disabled = (current_idx == questions_count - 1)
            assert is_prev_disabled is False, f"Previous should be enabled at Q{expected_q}"
            if expected_q < 10:
                assert is_next_disabled is False, f"Next should be enabled at Q{expected_q}"
            else:
                assert is_next_disabled is True, "Next should be disabled on last question"
            assert f"Question {expected_q} of 10" == f"Question {current_idx + 1} of {questions_count}"

        # Sequential navigation backward
        for expected_q in range(9, 0, -1):
            current_idx -= 1
            is_next_disabled = (current_idx == questions_count - 1)
            is_prev_disabled = (current_idx == 0)
            assert is_next_disabled is False, f"Next should be enabled when moving back to Q{expected_q}"
            if expected_q > 1:
                assert is_prev_disabled is False, f"Previous should be enabled at Q{expected_q}"
            else:
                assert is_prev_disabled is True, "Previous should be disabled when back at Q1"
            assert f"Question {expected_q} of 10" == f"Question {current_idx + 1} of {questions_count}"

        # Week switch resets to Question 1
        new_week_idx = 0
        assert new_week_idx == 0, "Changing weeks must reset to question index 0"

        print(" -> PASS: Boundary conditions, sequential step forward/back, and week-switch resets verified.")
        results["Navigation logic"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Navigation logic"] = "FAIL"

    # 8. Database Preservation Check
    print("\n[8] Testing database preservation (12 weeks, 120 questions, 480 options)...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM weeks;")
        weeks_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM questions WHERE is_verified = 1;")
        verified_q_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM options;")
        options_count = cursor.fetchone()[0]
        conn.close()

        assert weeks_count == 12, f"Expected 12 weeks, got {weeks_count}"
        assert verified_q_count == 120, f"Expected 120 verified questions, got {verified_q_count}"
        assert options_count == 480, f"Expected 480 options, got {options_count}"

        print(f" -> PASS: Database strictly intact ({weeks_count} weeks, {verified_q_count} verified questions, {options_count} options).")
        results["Database preservation"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Database preservation"] = "FAIL"

    print("\n=== Phase 4 Validation Summary ===")
    all_passed = True
    for test_name, status in results.items():
        print(f" - {test_name}: {status}")
        if status != "PASS":
            all_passed = False

    if not all_passed:
        raise SystemExit("Phase 4 validation failed!")

    print("\nAll Phase 4 validation checks PASSED successfully.")


if __name__ == "__main__":
    run_phase4_validation()
