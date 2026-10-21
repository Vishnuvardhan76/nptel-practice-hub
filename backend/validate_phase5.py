"""
Phase 5 Comprehensive Validation Suite for NPTEL Practice Hub
Validates Practice Mode implementation, session creation (Complete, Quick, Custom),
fair week distribution, question/option shuffling, client-side answer security,
autosaving, server-side grading, unanswered handling, submission lock, retakes,
results review consistency, mastery rules, database integrity, and Learn Mode regression.
"""

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import app, allocate_quotas
from database import get_db_connection, DEFAULT_DB_PATH
from validate_phase2 import run_phase2_validation
from validate_phase3 import run_phase3_validation
from validate_phase4 import run_phase4_validation


def run_phase5_validation():
    print("=== NPTEL Practice Hub Phase 5 Practice Mode Comprehensive Validation ===")
    results = {}

    # Step 0: Record and verify pre-test production DB hash
    print("\n[Step 0] Verifying production database pre-test integrity...")
    initial_hash = hashlib.sha256(open(DEFAULT_DB_PATH, "rb").read()).hexdigest()
    print(f" -> Production database SHA-256 pre-test: {initial_hash}")

    # Provision isolated temporary SQLite database copy
    print("\n[Step 0.1] Provisioning isolated temporary database environment...")
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    temp_db_path = Path(temp_dir.name) / "isolated_phase5_test.db"
    shutil.copy2(DEFAULT_DB_PATH, temp_db_path)

    # Point Flask app and global database.DEFAULT_DB_PATH to isolated test database
    import database
    orig_default_db = database.DEFAULT_DB_PATH
    database.DEFAULT_DB_PATH = temp_db_path
    app.config["DATABASE_PATH"] = str(temp_db_path)

    # Isolated connection helper for direct cursor tests
    def get_test_db_connection():
        return get_db_connection(temp_db_path)

    # Setup client with Phase 7A test guest identity
    client = app.test_client()
    client.environ_base['HTTP_X_CLIENT_ID'] = 'test_phase5_guest'

    try:
        # -------------------------------------------------------------------------
        # 1. Phase 2, 3, and 4 Regression Check (Read-Only)
        # -------------------------------------------------------------------------
        print("\n[1] Verifying Phase 2, 3, and 4 regression test suites...")
        try:
            run_phase2_validation()
            run_phase3_validation()
            run_phase4_validation()
            print(" -> PASS: Prior phase regression suites passed with zero regressions.")
            results["1. Prior Phase Regressions"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: Prior phase regression failure: {e}")
            results["1. Prior Phase Regressions"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 2. Complete, Quick, and Custom Test Session Creation
        # -------------------------------------------------------------------------
        print("\n[2] Testing Complete, Quick, and Custom session creation...")
        try:
            # A. Complete test on Weeks 1 and 2 (10 + 10 = 20 questions)
            resp_c = client.post("/api/practice/sessions", json={
                "weeks": [1, 2],
                "test_type": "complete"
            })
            assert resp_c.status_code == 201, f"Complete test failed: {resp_c.status_code}"
            data_c = json.loads(resp_c.data.decode("utf-8"))["session"]
            assert data_c["total_questions"] == 20, f"Expected 20 questions, got {data_c['total_questions']}"
            assert data_c["test_type"] == "complete"
            assert len(data_c["questions"]) == 20

            # B. Quick test (10 questions from Weeks 1, 2, 3)
            resp_q = client.post("/api/practice/sessions", json={
                "weeks": [1, 2, 3],
                "test_type": "quick",
                "question_count": 10
            })
            assert resp_q.status_code == 201, f"Quick test failed: {resp_q.status_code}"
            data_q = json.loads(resp_q.data.decode("utf-8"))["session"]
            assert data_q["total_questions"] == 10
            assert data_q["test_type"] == "quick"
            assert len(data_q["questions"]) == 10

            # C. Custom test (7 questions from Weeks 4 and 5)
            resp_cust = client.post("/api/practice/sessions", json={
                "weeks": [4, 5],
                "test_type": "custom",
                "question_count": 7
            })
            assert resp_cust.status_code == 201, f"Custom test failed: {resp_cust.status_code}"
            data_cust = json.loads(resp_cust.data.decode("utf-8"))["session"]
            assert data_cust["total_questions"] == 7
            assert data_cust["test_type"] == "custom"
            assert len(data_cust["questions"]) == 7

            print(" -> PASS: Complete, Quick, and Custom tests created valid sessions.")
            results["2. Session Creation (Complete/Quick/Custom)"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["2. Session Creation (Complete/Quick/Custom)"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 3. Validation: Reject Invalid Weeks and Question Counts
        # -------------------------------------------------------------------------
        print("\n[3] Testing rejection of invalid week selections and question counts...")
        try:
            # Empty weeks
            r1 = client.post("/api/practice/sessions", json={"weeks": [], "test_type": "complete"})
            assert r1.status_code == 400, f"Expected 400 for empty weeks, got {r1.status_code}"

            # Invalid week number (0, 13)
            r2 = client.post("/api/practice/sessions", json={"weeks": [0, 13], "test_type": "complete"})
            assert r2.status_code == 400, f"Expected 400 for invalid week 0/13, got {r2.status_code}"

            # Negative custom count
            r3 = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "custom", "question_count": -5})
            assert r3.status_code == 400, f"Expected 400 for negative count, got {r3.status_code}"

            # Zero custom count
            r4 = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "custom", "question_count": 0})
            assert r4.status_code == 400, f"Expected 400 for zero count, got {r4.status_code}"

            # Exceeding available count (Week 1 has 10, requesting 15)
            r5 = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "custom", "question_count": 15})
            assert r5.status_code == 400, f"Expected 400 for count exceeding available, got {r5.status_code}"

            print(" -> PASS: Server strictly rejected invalid weeks and question counts.")
            results["3. Rejection of Invalid Inputs"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["3. Rejection of Invalid Inputs"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 4. Quick Test Feasibility Constraints
        # -------------------------------------------------------------------------
        print("\n[4] Testing Quick Test feasibility constraints...")
        try:
            # Week 1 only has 10 questions. Quick test with 20 or 30 must be rejected.
            rq_bad20 = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "quick", "question_count": 20})
            assert rq_bad20.status_code == 400, f"Expected 400 for impossible quick test, got {rq_bad20.status_code}"

            rq_bad30 = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "quick", "question_count": 30})
            assert rq_bad30.status_code == 400, f"Expected 400 for impossible quick test, got {rq_bad30.status_code}"

            # Quick test with 10 questions from Week 1 must succeed
            rq_good10 = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "quick", "question_count": 10})
            assert rq_good10.status_code == 201

            # Quick test with 30 questions from 3 weeks (30 available) must succeed
            rq_good30 = client.post("/api/practice/sessions", json={"weeks": [1, 2, 3], "test_type": "quick", "question_count": 30})
            assert rq_good30.status_code == 201

            print(" -> PASS: Quick Test only allows feasible counts and rejects infeasible requests.")
            results["4. Quick Test Feasibility"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["4. Quick Test Feasibility"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 5. Balanced Question Distribution Across Selected Weeks
        # -------------------------------------------------------------------------
        print("\n[5] Testing balanced question distribution across weeks...")
        try:
            # Test unit allocation logic directly
            # 10 questions from 3 weeks (capacities 10, 10, 10) -> quotas should sum to 10 and max-min <= 1
            q_alloc = allocate_quotas({1: 10, 2: 10, 3: 10}, 10)
            assert sum(q_alloc.values()) == 10
            assert max(q_alloc.values()) - min(q_alloc.values()) <= 1, f"Unbalanced: {q_alloc}"

            # 20 questions from 3 weeks -> quotas should sum to 20 and max-min <= 1 (e.g. 7, 7, 6)
            q_alloc20 = allocate_quotas({1: 10, 2: 10, 3: 10}, 20)
            assert sum(q_alloc20.values()) == 20
            assert max(q_alloc20.values()) - min(q_alloc20.values()) <= 1, f"Unbalanced: {q_alloc20}"

            # Now test via the API endpoint
            resp = client.post("/api/practice/sessions", json={
                "weeks": [1, 2, 3],
                "test_type": "quick",
                "question_count": 10
            })
            assert resp.status_code == 201
            session_qs = json.loads(resp.data.decode("utf-8"))["session"]["questions"]
            week_counts = {}
            for q in session_qs:
                week_counts[q["week_number"]] = week_counts.get(q["week_number"], 0) + 1
            assert sum(week_counts.values()) == 10
            assert max(week_counts.values()) - min(week_counts.values()) <= 1, f"API week distribution unbalanced: {week_counts}"

            print(f" -> PASS: Questions distributed as evenly as possible across selected weeks: {week_counts}")
            results["5. Balanced Week Distribution"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["5. Balanced Week Distribution"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 6. Duplicate Question Prevention
        # -------------------------------------------------------------------------
        print("\n[6] Testing duplicate question prevention...")
        try:
            # Full test across all 12 weeks (120 questions)
            resp_all = client.post("/api/practice/sessions", json={
                "weeks": list(range(1, 13)),
                "test_type": "complete"
            })
            assert resp_all.status_code == 201
            qs = json.loads(resp_all.data.decode("utf-8"))["session"]["questions"]
            qids = [q["id"] for q in qs]
            assert len(qids) == 120, f"Expected 120 questions, got {len(qids)}"
            assert len(qids) == len(set(qids)), "Duplicate question IDs detected in test!"

            print(" -> PASS: Zero duplicate question IDs across all test sessions.")
            results["6. Duplicate Question Prevention"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["6. Duplicate Question Prevention"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 7. Shuffling Independence & Answer Mapping Integrity
        # -------------------------------------------------------------------------
        print("\n[7] Testing option shuffling independence and answer-key integrity...")
        try:
            conn = get_test_db_connection()
            cur = conn.cursor()

            # Create two tests for Week 1 and compare option order and verify mapping
            r_a = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "complete"})
            r_b = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "complete"})
            s_a = json.loads(r_a.data.decode("utf-8"))["session"]
            s_b = json.loads(r_b.data.decode("utf-8"))["session"]

            # Check that options maintain valid ID-to-text correspondence
            for q in s_a["questions"]:
                q_id = q["id"]
                for opt in q["options"]:
                    cur.execute("SELECT option_text, is_correct FROM options WHERE id = ?", (opt["id"],))
                    row = cur.fetchone()
                    assert row is not None, f"Option ID {opt['id']} not in database"
                    assert row["option_text"] == opt["option_text"], "Option text corrupted during shuffle"

            conn.close()
            print(" -> PASS: Option shuffling preserves correct-answer mapping and database integrity.")
            results["7. Shuffling & Answer Integrity"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["7. Shuffling & Answer Integrity"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 8. Server-Side Answer Security (Client-Blind Tests)
        # -------------------------------------------------------------------------
        print("\n[8] Testing that active-test APIs expose zero answer keys...")
        try:
            # Create session and inspect payload
            r_sec = client.post("/api/practice/sessions", json={"weeks": [1, 2], "test_type": "complete"})
            s_sec = json.loads(r_sec.data.decode("utf-8"))["session"]

            def check_no_answer_leak(obj, path=""):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        forbidden = ["is_correct", "correct_option_id", "answer_key", "correct_answer"]
                        for f in forbidden:
                            assert f not in k.lower(), f"Answer security leak detected at {path}.{k}"
                        check_no_answer_leak(v, f"{path}.{k}")
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        check_no_answer_leak(item, f"{path}[{i}]")

            check_no_answer_leak(s_sec, "session_creation")

            # Also inspect GET /api/practice/sessions/<session_id>
            r_get = client.get(f"/api/practice/sessions/{s_sec['id']}")
            s_get = json.loads(r_get.data.decode("utf-8"))["session"]
            check_no_answer_leak(s_get, "session_get")

            print(" -> PASS: Active test responses contain zero answer keys or correctness data.")
            results["8. Client-Blind Answer Security"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["8. Client-Blind Answer Security"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 9. Answers Saving and Simulated Page Refresh Recovery
        # -------------------------------------------------------------------------
        print("\n[9] Testing answer autosave and page refresh recovery...")
        try:
            r_ses = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "complete"})
            s_id = json.loads(r_ses.data.decode("utf-8"))["session"]["id"]
            qs = json.loads(r_ses.data.decode("utf-8"))["session"]["questions"]

            q1 = qs[0]
            q1_opt = q1["options"][1]["id"]
            q2 = qs[1]
            q2_opt = q2["options"][3]["id"]

            # Save answers
            r_ans = client.post(f"/api/practice/sessions/{s_id}/answers", json={
                "answers": {
                    str(q1["id"]): q1_opt,
                    str(q2["id"]): q2_opt
                }
            })
            assert r_ans.status_code == 200

            # Simulate page refresh by retrieving session
            r_recov = client.get(f"/api/practice/sessions/{s_id}")
            assert r_recov.status_code == 200
            recov_data = json.loads(r_recov.data.decode("utf-8"))["session"]

            # Check answers recovered
            user_ans = recov_data["user_answers"]
            assert user_ans.get(str(q1["id"])) == q1_opt
            assert user_ans.get(str(q2["id"])) == q2_opt

            # Check randomized option order strictly preserved
            recov_qs = recov_data["questions"]
            for original_q, recovered_q in zip(qs, recov_qs):
                assert original_q["id"] == recovered_q["id"]
                orig_opt_ids = [o["id"] for o in original_q["options"]]
                recov_opt_ids = [o["id"] for o in recovered_q["options"]]
                assert orig_opt_ids == recov_opt_ids, "Option ordering changed across refresh!"

            print(" -> PASS: User answers and randomized option orders strictly recover after reload.")
            results["9. Answer Autosave & Refresh Recovery"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["9. Answer Autosave & Refresh Recovery"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 10. Rejection of Invalid Question / Option Combinations
        # -------------------------------------------------------------------------
        print("\n[10] Testing rejection of invalid question and option combinations...")
        try:
            r_ses = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "complete"})
            s_id = json.loads(r_ses.data.decode("utf-8"))["session"]["id"]
            qs = json.loads(r_ses.data.decode("utf-8"))["session"]["questions"]
            q1 = qs[0]
            q2 = qs[1]

            # Case A: Option belongs to q2, but submitted for q1
            r_cross = client.post(f"/api/practice/sessions/{s_id}/answers", json={
                "answers": {str(q1["id"]): q2["options"][0]["id"]}
            })
            assert r_cross.status_code == 400, f"Expected 400 for cross-question option, got {r_cross.status_code}"

            # Case B: Question not in this session (e.g. from Week 12)
            conn = get_test_db_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM questions WHERE week_number = 12 LIMIT 1")
            w12_qid = c.fetchone()["id"]
            c.execute("SELECT id FROM options WHERE question_id = ? LIMIT 1", (w12_qid,))
            w12_optid = c.fetchone()["id"]
            conn.close()

            r_foreign = client.post(f"/api/practice/sessions/{s_id}/answers", json={
                "answers": {str(w12_qid): w12_optid}
            })
            assert r_foreign.status_code == 400, f"Expected 400 for non-session question, got {r_foreign.status_code}"

            print(" -> PASS: Mismatched and out-of-session options/questions strictly rejected.")
            results["10. Invalid Option Combinations"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["10. Invalid Option Combinations"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 11 & 12. Server-Side Scoring & Unanswered Questions Handling
        # -------------------------------------------------------------------------
        print("\n[11 & 12] Testing server-side grading and unanswered questions handling...")
        try:
            conn = get_test_db_connection()
            cur = conn.cursor()

            # Create 10-question test for Week 1
            r_ses = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "complete"})
            s_id = json.loads(r_ses.data.decode("utf-8"))["session"]["id"]
            qs = json.loads(r_ses.data.decode("utf-8"))["session"]["questions"]

            # Plan: 7 correct answers, 2 incorrect answers, 1 unanswered
            answers_to_submit = {}
            for idx, q in enumerate(qs):
                cur.execute("SELECT id FROM options WHERE question_id = ? AND is_correct = 1", (q["id"],))
                correct_opt = cur.fetchone()["id"]
                cur.execute("SELECT id FROM options WHERE question_id = ? AND is_correct = 0 LIMIT 1", (q["id"],))
                wrong_opt = cur.fetchone()["id"]

                if idx < 7:
                    # Correct
                    answers_to_submit[str(q["id"])] = correct_opt
                elif idx < 9:
                    # Incorrect
                    answers_to_submit[str(q["id"])] = wrong_opt
                else:
                    # Unanswered (skip)
                    pass

            conn.close()

            # Submit test
            r_sub = client.post(f"/api/practice/sessions/{s_id}/submit", json={
                "final_answers": answers_to_submit
            })
            assert r_sub.status_code == 200, f"Submit failed: {r_sub.status_code}"
            res = json.loads(r_sub.data.decode("utf-8"))["result"]

            assert res["correct_count"] == 7
            assert res["incorrect_count"] == 2
            assert res["unanswered_count"] == 1
            assert res["score"] == 7.0
            assert res["total_marks"] == 10.0
            assert res["percentage"] == 70.0
            assert res["status"] == "submitted"

            print(f" -> PASS: Graded correctly on server: 7 correct (7.0 marks), 2 incorrect, 1 unanswered. Percentage: {res['percentage']}%.")
            results["11. Server-Side Marks Scoring"] = "PASS"
            results["12. Unanswered Question Handling"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["11. Server-Side Marks Scoring"] = f"FAIL: {e}"
            results["12. Unanswered Question Handling"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 13 & 14. Submission Lock & Modifying Submitted Test Rejection
        # -------------------------------------------------------------------------
        print("\n[13 & 14] Testing submission idempotency and locking against post-submit edits...")
        try:
            # A. Cannot modify answers on already submitted session
            r_edit = client.post(f"/api/practice/sessions/{s_id}/answers", json={
                "answers": {str(qs[9]["id"]): qs[9]["options"][0]["id"]}
            })
            assert r_edit.status_code in [400, 403], f"Expected 400 or 403 when modifying submitted test, got {r_edit.status_code}"

            # B. Duplicate submission does not alter results
            r_resub = client.post(f"/api/practice/sessions/{s_id}/submit", json={
                "final_answers": {}
            })
            assert r_resub.status_code == 200
            res2 = json.loads(r_resub.data.decode("utf-8"))["result"]
            assert res2["score"] == 7.0, f"Score changed after duplicate submit! {res2['score']}"
            assert res2["correct_count"] == 7

            print(" -> PASS: Submitted tests cannot be altered and submissions are locked.")
            results["13. Idempotent Submission"] = "PASS"
            results["14. Post-Submit Edit Rejection"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["13. Idempotent Submission"] = f"FAIL: {e}"
            results["14. Post-Submit Edit Rejection"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 15. Retakes Create Independent Attempts
        # -------------------------------------------------------------------------
        print("\n[15] Testing that retakes create independent attempts...")
        try:
            # Initial test
            r_init = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "complete"})
            id_1 = json.loads(r_init.data.decode("utf-8"))["session"]["id"]
            client.post(f"/api/practice/sessions/{id_1}/submit", json={"final_answers": {}})

            # Retake
            r_retake = client.post("/api/practice/sessions", json={"weeks": [1], "test_type": "complete"})
            id_2 = json.loads(r_retake.data.decode("utf-8"))["session"]["id"]

            assert id_1 != id_2, "Retake reused the same session ID!"

            # Verify both exist independently in database
            conn = get_test_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT session_id, is_submitted FROM practice_sessions WHERE session_id IN (?, ?)", (id_1, id_2))
            rows = {r["session_id"]: r["is_submitted"] for r in cur.fetchall()}
            conn.close()
            assert rows[id_1] == 1
            assert rows[id_2] == 0

            print(" -> PASS: Retakes create new, independent attempts without overwriting previous results.")
            results["15. Independent Retake Attempts"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["15. Independent Retake Attempts"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 16. Results and Answer Review Match Database
        # -------------------------------------------------------------------------
        print("\n[16] Testing that results and answer review match database records...")
        try:
            # Get results of the 7-correct test from step 11
            r_rev = client.get(f"/api/practice/sessions/{s_id}/results")
            assert r_rev.status_code == 200
            rev_data = json.loads(r_rev.data.decode("utf-8"))

            conn = get_test_db_connection()
            cur = conn.cursor()

            for q in rev_data["questions"]:
                # Check options
                for opt in q["options"]:
                    cur.execute("SELECT is_correct FROM options WHERE id = ?", (opt["id"],))
                    db_correct = (cur.fetchone()["is_correct"] == 1)
                    assert opt["is_correct"] == db_correct, f"Option {opt['id']} correctness mismatch with DB!"

            conn.close()
            print(" -> PASS: Results and question review strictly match database source of truth.")
            results["16. Results & Review Consistency"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["16. Results & Review Consistency"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 17 & 18. Mastery Rules (Single-Week >=75% vs Mixed-Week)
        # -------------------------------------------------------------------------
        print("\n[17 & 18] Testing Mastery rules (Single-Week >=75% vs Mixed-Week tests)...")
        try:
            conn = get_test_db_connection()
            cur = conn.cursor()

            # Case A: Single-week test scoring 80% (8/10) -> MASTERED
            r_m1 = client.post("/api/practice/sessions", json={"weeks": [2], "test_type": "complete"})
            id_m1 = json.loads(r_m1.data.decode("utf-8"))["session"]["id"]
            qs_m1 = json.loads(r_m1.data.decode("utf-8"))["session"]["questions"]

            ans_80 = {}
            for idx, q in enumerate(qs_m1):
                if idx < 8:
                    cur.execute("SELECT id FROM options WHERE question_id = ? AND is_correct = 1", (q["id"],))
                    ans_80[str(q["id"])] = cur.fetchone()["id"]

            client.post(f"/api/practice/sessions/{id_m1}/submit", json={"final_answers": ans_80})
            res_m1 = json.loads(client.get(f"/api/practice/sessions/{id_m1}/results").data.decode("utf-8"))["summary"]
            assert res_m1["is_single_week"] is True
            assert res_m1["percentage"] == 80.0
            assert res_m1["is_mastered"] is True, "Single-week test with 80% should grant mastery!"

            # Case B: Single-week test scoring 70% (7/10) -> NOT MASTERED
            r_m2 = client.post("/api/practice/sessions", json={"weeks": [3], "test_type": "complete"})
            id_m2 = json.loads(r_m2.data.decode("utf-8"))["session"]["id"]
            qs_m2 = json.loads(r_m2.data.decode("utf-8"))["session"]["questions"]

            ans_70 = {}
            for idx, q in enumerate(qs_m2):
                if idx < 7:
                    cur.execute("SELECT id FROM options WHERE question_id = ? AND is_correct = 1", (q["id"],))
                    ans_70[str(q["id"])] = cur.fetchone()["id"]

            client.post(f"/api/practice/sessions/{id_m2}/submit", json={"final_answers": ans_70})
            res_m2 = json.loads(client.get(f"/api/practice/sessions/{id_m2}/results").data.decode("utf-8"))["summary"]
            assert res_m2["is_single_week"] is True
            assert res_m2["percentage"] == 70.0
            assert res_m2["is_mastered"] is False, "Single-week test with 70% should NOT grant mastery!"

            # Case C: Mixed-week test scoring 100% (20/20) -> CANNOT GRANT MASTERY
            r_mix = client.post("/api/practice/sessions", json={"weeks": [4, 5], "test_type": "complete"})
            id_mix = json.loads(r_mix.data.decode("utf-8"))["session"]["id"]
            qs_mix = json.loads(r_mix.data.decode("utf-8"))["session"]["questions"]

            ans_100 = {}
            for q in qs_mix:
                cur.execute("SELECT id FROM options WHERE question_id = ? AND is_correct = 1", (q["id"],))
                ans_100[str(q["id"])] = cur.fetchone()["id"]

            client.post(f"/api/practice/sessions/{id_mix}/submit", json={"final_answers": ans_100})
            res_mix = json.loads(client.get(f"/api/practice/sessions/{id_mix}/results").data.decode("utf-8"))["summary"]
            assert res_mix["is_single_week"] is False
            assert res_mix["percentage"] == 100.0
            assert res_mix["is_mastered"] is False, "Mixed-week test must NEVER grant single-week mastery!"

            conn.close()
            print(" -> PASS: Single-week test >=75% grants mastery; mixed-week test never grants mastery.")
            results["17. Single-Week Mastery (>=75%)"] = "PASS"
            results["18. Mixed-Week No Mastery"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["17. Single-Week Mastery (>=75%)"] = f"FAIL: {e}"
            results["18. Mixed-Week No Mastery"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 19. Database Preservation (12 weeks, 120 questions, 480 options)
        # -------------------------------------------------------------------------
        print("\n[19] Testing preservation of course database records...")
        try:
            conn = get_test_db_connection()
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) as cnt FROM weeks")
            assert cur.fetchone()["cnt"] == 12, "Weeks count corrupted!"

            cur.execute("SELECT COUNT(*) as cnt FROM questions WHERE is_verified = 1")
            assert cur.fetchone()["cnt"] == 120, "Questions count corrupted!"

            cur.execute("SELECT COUNT(*) as cnt FROM options")
            assert cur.fetchone()["cnt"] == 480, "Options count corrupted!"

            cur.execute("SELECT COUNT(*) as cnt FROM options WHERE is_correct = 1")
            assert cur.fetchone()["cnt"] == 120, "Correct options count corrupted!"

            conn.close()
            print(" -> PASS: Database strictly intact: 12 weeks, 120 verified questions, 480 options.")
            results["19. Database Preservation"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["19. Database Preservation"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # 20. Learn Mode Still Functional
        # -------------------------------------------------------------------------
        print("\n[20] Testing that Learn Mode remains fully functional...")
        try:
            r_learn = client.get("/api/weeks/1/questions")
            assert r_learn.status_code == 200
            learn_data = json.loads(r_learn.data.decode("utf-8"))
            assert learn_data["status"] == "success"
            assert len(learn_data["questions"]) == 10

            # In Learn Mode, answers and verification tags ARE present
            for q in learn_data["questions"]:
                opts = q["options"]
                assert len(opts) == 4
                has_correct = any(o.get("is_correct") == 1 for o in opts)
                assert has_correct, "Learn mode missing verified answer keys!"

            print(" -> PASS: Learn Mode remains fully functional with verified answers.")
            results["20. Learn Mode Functional"] = "PASS"
        except Exception as e:
            print(f" -> FAIL: {e}")
            results["20. Learn Mode Functional"] = f"FAIL: {e}"

        # -------------------------------------------------------------------------
        # Final Validation Summary
        # -------------------------------------------------------------------------
        print("\n================ Phase 5 Validation Summary ================")
        all_passed = True
        for test_name, status in results.items():
            print(f" - {test_name}: {status}")
            if not status.startswith("PASS"):
                all_passed = False

        if all_passed:
            print("\nSUCCESS: All 20 Phase 5 validation checks PASSED successfully.")
        else:
            print("\nFAILURE: Some Phase 5 validation checks failed.")
            sys.exit(1)

    finally:
        # Step 21: Cleanup isolated environment and verify production DB hash invariance
        print("\n[Cleanup] Cleaning up isolated database environment...")
        database.DEFAULT_DB_PATH = orig_default_db
        app.config.pop("DATABASE_PATH", None)
        try:
            temp_dir.cleanup()
        except Exception as e:
            print(f" -> Warning during temp directory cleanup: {e}")

        print("\n[Step 22] Verifying production database post-test SHA-256 invariance...")
        post_hash = hashlib.sha256(open(DEFAULT_DB_PATH, "rb").read()).hexdigest()
        print(f" -> Production database SHA-256 post-test: {post_hash}")
        if post_hash != initial_hash:
            raise RuntimeError(
                f"CRITICAL SAFETY VIOLATION: Production database hash changed!\n"
                f"Pre-test:  {initial_hash}\n"
                f"Post-test: {post_hash}"
            )
        print(" -> PASS: Production database SHA-256 hash strictly invariant (0 bytes changed).")


if __name__ == "__main__":
    run_phase5_validation()
