"""
NPTEL Practice Hub - Flask Application Foundation
Provides basic health check and read-only week metadata API endpoints.
Preserves existing SQLite database and strictly isolates correct answer keys.
"""

import json
import random
import re
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from flask import Flask, jsonify, request, send_from_directory

# Resolve backend and frontend base paths relative to this file
BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = (BACKEND_DIR.parent / "frontend").resolve()

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import get_db_connection

app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIR),
    static_url_path=""
)


def get_db():
    """
    Use PostgreSQL on deployment when DATABASE_URL is configured.
    Keep SQLite as the default for local development and isolated tests.
    """
    import os

    database_url = os.environ.get("DATABASE_URL")
    db_path = app.config.get("DATABASE_PATH")

    if database_url and not db_path:
        from postgres.database import get_postgres_connection
        return get_postgres_connection(database_url)

    return get_db_connection(db_path)


# Restricted local development CORS origins
ALLOWED_ORIGINS = {
    "http://127.0.0.1:5000",
    "http://localhost:5000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "null"  # file:// origin in Chromium browsers
}


@app.after_request
def apply_cors_headers(response):
    """
    Enables CORS strictly for allowed local development origins.
    Does not use a wildcard origin.
    """
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept, X-Client-ID"
        response.headers["Vary"] = "Origin"
    return response


# --- Client Identity & Session Ownership Helpers ---

CLIENT_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{5,64}$")


def is_valid_client_id(client_id: Optional[str]) -> bool:
    """Validates that client_id is a non-empty string adhering to expected length and characters."""
    if not client_id or not isinstance(client_id, str):
        return False
    return bool(CLIENT_ID_REGEX.match(client_id.strip()))


def get_request_client_id() -> Optional[str]:
    """
    Extracts client identity from X-Client-ID header, query parameter, or JSON body.
    """
    # 1. Header (standard transmission)
    cid = request.headers.get("X-Client-ID")
    if cid and cid.strip():
        return cid.strip()

    # 2. Query param
    cid = request.args.get("client_id")
    if cid and cid.strip():
        return cid.strip()

    # 3. JSON body
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if isinstance(data, dict):
            cid = data.get("client_id")
            if cid and isinstance(cid, str) and cid.strip():
                return cid.strip()

    return None


def check_session_ownership(session: Any) -> Tuple[bool, Optional[Any], int]:
    """
    Verifies that the requesting client owns the target practice session.
    Mandatory legacy protection: sessions with NULL/empty client_id cannot be verified
    and are strictly rejected with HTTP 403 to prevent unauthenticated access.
    """
    session_owner = session["client_id"] if "client_id" in session.keys() else None

    # Legacy session protection: never expose or modify legacy unowned sessions
    if not session_owner:
        return False, jsonify({
            "status": "error",
            "message": "Access denied: session ownership cannot be verified (legacy unowned session)."
        }), 403

    client_id = get_request_client_id()
    if not client_id:
        return False, jsonify({
            "status": "error",
            "message": "Client identity required to access this session."
        }), 401

    if not is_valid_client_id(client_id):
        return False, jsonify({
            "status": "error",
            "message": "Invalid client_id format."
        }), 400

    if client_id != session_owner:
        return False, jsonify({
            "status": "error",
            "message": "Access denied: this session belongs to another client."
        }), 403

    return True, None, 200


# --- Static Frontend Serving ---

@app.route("/", methods=["GET"])
def serve_index():
    """Serves the frontend single-page dashboard."""
    if (FRONTEND_DIR / "index.html").exists():
        return send_from_directory(FRONTEND_DIR, "index.html")
    return jsonify({"message": "NPTEL Practice Hub Backend API", "frontend_path": str(FRONTEND_DIR)})


@app.route("/assets/<path:path>", methods=["GET"])
def serve_assets(path):
    """Serves static frontend assets (css, js, etc.)."""
    return send_from_directory(FRONTEND_DIR / "assets", path)


# --- REST API Endpoints ---

@app.route("/api/health", methods=["GET"])
def health_check():
    """
    Health check endpoint.
    Returns status confirming the Flask service is active.
    """
    return jsonify({
        "status": "healthy",
        "service": "NPTEL Practice Hub API",
        "version": "1.0.0"
    }), 200


@app.route("/api/weeks", methods=["GET"])
def get_weeks():
    """
    Read-only endpoint returning week metadata and question counts.
    STRICT SECURITY RULE: Never returns correct answers, options, or answer keys.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Query week metadata along with verified question counts
        cursor.execute("""
            SELECT w.week_number,
                   w.title,
                   w.total_questions,
                   COUNT(q.id) as question_count,
                   SUM(CASE WHEN q.is_verified = 1 THEN 1 ELSE 0 END) as verified_questions
            FROM weeks w
            LEFT JOIN questions q ON w.week_number = q.week_number
            GROUP BY w.week_number
            ORDER BY w.week_number ASC;
        """)
        rows = cursor.fetchall()
        conn.close()

        weeks_list = []
        for r in rows:
            weeks_list.append({
                "week_number": r["week_number"],
                "title": r["title"],
                "total_questions": r["total_questions"],
                "verified_questions": r["verified_questions"] if r["verified_questions"] is not None else 0
            })

        return jsonify({
            "status": "success",
            "count": len(weeks_list),
            "weeks": weeks_list
        }), 200

    except Exception:
        import logging
        logging.exception("Failed to retrieve week metadata")
        return jsonify({
            "status": "error",
            "message": "Failed to retrieve week metadata."
        }), 500


@app.route("/api/weeks/<week_identifier>/questions", methods=["GET"])
def get_week_questions(week_identifier):
    """
    Learn Mode endpoint returning verified questions and options in original order.
    Exposes verified correct answers explicitly for untimed study mode.
    Validates week parameter safely and never leaks internal details.
    """
    # 1. Parameter Validation
    try:
        week_number = int(week_identifier)
        if week_number < 1:
            return jsonify({
                "status": "error",
                "message": "Invalid week number. Week number must be a positive integer."
            }), 400
    except (ValueError, TypeError):
        return jsonify({
            "status": "error",
            "message": "Invalid week parameter. Week number must be an integer."
        }), 400

    # 2. Database Retrieval
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Check if requested week exists
        cursor.execute(
            "SELECT week_number, title, total_questions FROM weeks WHERE week_number = ?;",
            (week_number,)
        )
        week = cursor.fetchone()
        if not week:
            conn.close()
            return jsonify({
                "status": "error",
                "message": f"Week {week_number} not found."
            }), 404

        # Retrieve verified questions in original order
        cursor.execute("""
            SELECT id, week_number, question_number, question_order, question_text, marks, is_verified
            FROM questions
            WHERE week_number = ? AND is_verified = 1
            ORDER BY question_order ASC;
        """, (week_number,))
        questions_rows = cursor.fetchall()

        # Retrieve all options for verified questions in original order
        cursor.execute("""
            SELECT o.id, o.question_id, o.option_letter, o.option_order, o.option_text, o.is_correct
            FROM options o
            JOIN questions q ON o.question_id = q.id
            WHERE q.week_number = ? AND q.is_verified = 1
            ORDER BY o.question_id ASC, o.option_order ASC;
        """, (week_number,))
        options_rows = cursor.fetchall()
        conn.close()

        # Group options by question_id
        options_by_q = {}
        for opt in options_rows:
            q_id = opt["question_id"]
            if q_id not in options_by_q:
                options_by_q[q_id] = []
            options_by_q[q_id].append({
                "id": opt["id"],
                "option_letter": opt["option_letter"],
                "option_order": opt["option_order"],
                "option_text": opt["option_text"],
                "is_correct": int(opt["is_correct"])
            })

        # Assemble questions array preserving question_number and question_order
        questions_list = []
        for q in questions_rows:
            q_id = q["id"]
            questions_list.append({
                "id": q_id,
                "week_number": q["week_number"],
                "question_number": q["question_number"],
                "question_order": q["question_order"],
                "question_text": q["question_text"],
                "marks": float(q["marks"]),
                "is_verified": int(q["is_verified"]),
                "options": options_by_q.get(q_id, [])
            })

        return jsonify({
            "status": "success",
            "week_number": week["week_number"],
            "title": week["title"],
            "total_questions": len(questions_list),
            "questions": questions_list
        }), 200

    except Exception:
        return jsonify({
            "status": "error",
            "message": "An error occurred while retrieving questions."
        }), 500


# --- Practice Mode Helper Functions ---

def allocate_quotas(capacities: Dict[int, int], target: int) -> Dict[int, int]:
    """
    Distributes target count as evenly as possible across weeks based on their capacities.
    If a week cannot contribute the requested number, distributes remainder among other weeks.
    """
    total_cap = sum(capacities.values())
    if target > total_cap:
        raise ValueError(f"Target count {target} exceeds total capacity {total_cap}")
    if target == total_cap:
        return dict(capacities)

    alloc = {w: 0 for w in capacities}
    remaining = target

    while remaining > 0:
        active_weeks = [w for w in capacities if alloc[w] < capacities[w]]
        if not active_weeks:
            break
        share = max(1, remaining // len(active_weeks))
        for w in active_weeks:
            if remaining == 0:
                break
            give = min(share, capacities[w] - alloc[w], remaining)
            alloc[w] += give
            remaining -= give

    return alloc


# --- Practice Mode Endpoints ---

@app.route("/api/practice/sessions", methods=["POST", "OPTIONS"])
def create_practice_session():
    """
    Creates a new practice session with selected weeks, test type, and question count.
    Randomizes questions independently from options.
    STRICT SECURITY RULE: Never returns is_correct, correct option IDs, or answer keys.
    """
    if request.method == "OPTIONS":
        return "", 200

    try:
        data = request.get_json(silent=True) or {}
        selected_weeks = data.get("selected_weeks") if data.get("selected_weeks") is not None else data.get("weeks")
        test_type = data.get("test_type")
        question_count = data.get("question_count")
        client_id = get_request_client_id()
        if not is_valid_client_id(client_id):
            return jsonify({
                "status": "error",
                "message": "A valid client_id is required to create a practice session."
            }), 400

        # 1. Validate selected_weeks
        if not isinstance(selected_weeks, list) or len(selected_weeks) == 0:
            return jsonify({
                "status": "error",
                "message": "At least one week must be selected."
            }), 400

        validated_weeks = []
        for w in selected_weeks:
            try:
                w_int = int(w)
                if w_int < 1 or w_int > 12:
                    return jsonify({
                        "status": "error",
                        "message": f"Week {w} is out of valid range (Weeks 1 to 12)."
                    }), 400
                if w_int not in validated_weeks:
                    validated_weeks.append(w_int)
            except (ValueError, TypeError):
                return jsonify({
                    "status": "error",
                    "message": f"Invalid week identifier: {w}."
                }), 400

        validated_weeks.sort()

        conn = get_db()
        cursor = conn.cursor()

        # 2. Query verified questions for selected weeks
        placeholders = ",".join("?" for _ in validated_weeks)
        cursor.execute(f"""
            SELECT id, week_number, question_number, question_order, question_text, marks
            FROM questions
            WHERE week_number IN ({placeholders}) AND is_verified = 1
            ORDER BY week_number, question_order;
        """, validated_weeks)
        all_verified = [dict(r) for r in cursor.fetchall()]

        if not all_verified:
            conn.close()
            return jsonify({
                "status": "error",
                "message": "No verified questions available for the selected weeks."
            }), 400

        total_available = len(all_verified)
        questions_by_week: Dict[int, List[Dict[str, Any]]] = {}
        for q in all_verified:
            w_num = q["week_number"]
            if w_num not in questions_by_week:
                questions_by_week[w_num] = []
            questions_by_week[w_num].append(q)

        capacities = {w: len(questions_by_week.get(w, [])) for w in validated_weeks}

        # 3. Validate test_type and target_count
        if test_type == "complete":
            target_count = total_available
        elif test_type in ["quick_10", "quick_20", "quick_30"] or test_type == "quick":
            if test_type.startswith("quick_"):
                requested_num = int(test_type.split("_")[1])
            else:
                try:
                    requested_num = int(question_count)
                    if requested_num not in [10, 20, 30]:
                        conn.close()
                        return jsonify({
                            "status": "error",
                            "message": "Quick test question count must be 10, 20, or 30."
                        }), 400
                except (ValueError, TypeError):
                    conn.close()
                    return jsonify({
                        "status": "error",
                        "message": "Quick test requires a valid count of 10, 20, or 30."
                    }), 400

            if total_available < requested_num:
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": f"Selected weeks have {total_available} questions, which is fewer than the {requested_num} required for this Quick Test."
                }), 400
            target_count = requested_num
            test_type = "quick"
        elif test_type == "custom":
            try:
                qc = int(question_count)
                if qc < 1 or qc > total_available:
                    conn.close()
                    return jsonify({
                        "status": "error",
                        "message": f"Question count must be between 1 and {total_available} for selected weeks."
                    }), 400
                target_count = qc
            except (ValueError, TypeError):
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": "Custom question count must be a valid positive integer."
                }), 400
        else:
            conn.close()
            return jsonify({
                "status": "error",
                "message": "Invalid test type. Must be 'complete', 'quick', or 'custom'."
            }), 400

        # 4. Allocate quotas and sample questions
        allocations = allocate_quotas(capacities, target_count)
        selected_questions: List[Dict[str, Any]] = []
        for w, count in allocations.items():
            if count > 0:
                sampled = random.sample(questions_by_week[w], count)
                selected_questions.extend(sampled)

        # Randomize question order independently
        random.shuffle(selected_questions)

        # 5. Fetch and randomize options independently for each question
        question_ids = [q["id"] for q in selected_questions]
        q_placeholders = ",".join("?" for _ in question_ids)
        cursor.execute(f"""
            SELECT id, question_id, option_letter, option_order, option_text, is_correct
            FROM options
            WHERE question_id IN ({q_placeholders})
            ORDER BY question_id, option_order;
        """, question_ids)
        all_options = [dict(r) for r in cursor.fetchall()]

        options_by_q: Dict[int, List[Dict[str, Any]]] = {}
        for opt in all_options:
            q_id = opt["question_id"]
            if q_id not in options_by_q:
                options_by_q[q_id] = []
            options_by_q[q_id].append(opt)

        option_orders: Dict[str, List[int]] = {}
        client_questions: List[Dict[str, Any]] = []

        for q in selected_questions:
            q_id = q["id"]
            opts = list(options_by_q.get(q_id, []))
            # Randomize option order independently
            random.shuffle(opts)
            option_orders[str(q_id)] = [o["id"] for o in opts]

            # Build client-safe options without is_correct
            clean_opts = []
            for idx, o in enumerate(opts):
                clean_opts.append({
                    "id": o["id"],
                    "option_letter": chr(ord('a') + idx),
                    "option_text": o["option_text"]
                })

            client_questions.append({
                "id": q_id,
                "week_number": q["week_number"],
                "question_text": q["question_text"],
                "marks": float(q["marks"]),
                "options": clean_opts
            })

        # 6. Persist practice session in database
        session_id = str(uuid.uuid4())
        total_marks = sum(float(q["marks"]) for q in selected_questions)

        cursor.execute("""
            INSERT INTO practice_sessions (
                session_id, selected_weeks, test_type, question_ids, option_orders,
                user_answers, is_submitted, client_id, score, total_marks,
                correct_count, incorrect_count, unanswered_count
            ) VALUES (?, ?, ?, ?, ?, '{}', 0, ?, 0.0, ?, 0, 0, ?);
        """, (
            session_id,
            json.dumps(validated_weeks),
            test_type,
            json.dumps(question_ids),
            json.dumps(option_orders),
            client_id,
            total_marks,
            len(question_ids)
        ))
        conn.commit()
        conn.close()

        session_data = {
            "id": session_id,
            "session_id": session_id,
            "status": "active",
            "test_type": test_type,
            "selected_weeks": validated_weeks,
            "total_questions": len(client_questions),
            "total_marks": total_marks,
            "is_submitted": 0,
            "questions": client_questions,
            "user_answers": {}
        }

        return jsonify({
            "status": "success",
            "session": session_data,
            **session_data
        }), 201

    except Exception:
        return jsonify({
            "status": "error",
            "message": "An error occurred while creating the practice session."
        }), 500


@app.route("/api/practice/sessions/<session_id>", methods=["GET"])
def get_practice_session(session_id):
    """
    Retrieves or resumes an active practice session.
    Preserves exact session question sequence and randomized option order.
    STRICT SECURITY RULE: Never exposes answer keys or is_correct for active tests.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT session_id, created_at, selected_weeks, test_type, question_ids,
                   option_orders, user_answers, is_submitted, total_marks, score, client_id
            FROM practice_sessions
            WHERE session_id = ?;
        """, (session_id,))
        session = cursor.fetchone()

        if not session:
            conn.close()
            return jsonify({
                "status": "error",
                "message": "Practice session not found."
            }), 404

        # Validate session ownership
        ok, err_resp, status_code = check_session_ownership(session)
        if not ok:
            conn.close()
            return err_resp, status_code

        is_submitted = bool(session["is_submitted"])
        selected_weeks = json.loads(session["selected_weeks"])
        question_ids = json.loads(session["question_ids"])
        option_orders = json.loads(session["option_orders"])
        user_answers = json.loads(session["user_answers"] or "{}")

        if is_submitted:
            conn.close()
            sub_data = {
                "id": session["session_id"],
                "session_id": session["session_id"],
                "status": "submitted",
                "is_submitted": 1,
                "score": float(session["score"] or 0.0),
                "total_marks": float(session["total_marks"] or 0.0),
                "message": "This practice test has already been submitted."
            }
            return jsonify({
                "status": "success",
                "session": sub_data,
                **sub_data
            }), 200

        # Retrieve questions in preserved question_ids order
        q_placeholders = ",".join("?" for _ in question_ids)
        cursor.execute(f"""
            SELECT id, week_number, question_number, question_order, question_text, marks
            FROM questions
            WHERE id IN ({q_placeholders});
        """, question_ids)
        q_rows = {r["id"]: dict(r) for r in cursor.fetchall()}

        # Retrieve all options for these questions
        cursor.execute(f"""
            SELECT id, question_id, option_letter, option_text
            FROM options
            WHERE question_id IN ({q_placeholders});
        """, question_ids)
        opt_rows = {r["id"]: dict(r) for r in cursor.fetchall()}
        conn.close()

        client_questions = []
        for q_id in question_ids:
            if q_id not in q_rows:
                continue
            q_data = q_rows[q_id]
            stored_opt_ids = option_orders.get(str(q_id), [])

            clean_opts = []
            for idx, opt_id in enumerate(stored_opt_ids):
                if opt_id in opt_rows:
                    clean_opts.append({
                        "id": opt_id,
                        "option_letter": chr(ord('a') + idx),
                        "option_text": opt_rows[opt_id]["option_text"]
                    })

            client_questions.append({
                "id": q_id,
                "week_number": q_data["week_number"],
                "question_text": q_data["question_text"],
                "marks": float(q_data["marks"]),
                "options": clean_opts
            })

        session_data = {
            "id": session["session_id"],
            "session_id": session["session_id"],
            "status": "active",
            "test_type": session["test_type"],
            "selected_weeks": selected_weeks,
            "total_questions": len(client_questions),
            "total_marks": float(session["total_marks"] or 0.0),
            "is_submitted": 0,
            "questions": client_questions,
            "user_answers": user_answers
        }

        return jsonify({
            "status": "success",
            "session": session_data,
            **session_data
        }), 200

    except Exception:
        return jsonify({
            "status": "error",
            "message": "An error occurred while retrieving the practice session."
        }), 500


@app.route("/api/practice/sessions/<session_id>/answers", methods=["POST", "PUT", "OPTIONS"])
def save_practice_answers(session_id):
    """
    Saves or updates user's selected answers for an active practice session.
    Validates question IDs and option IDs against session configuration.
    Rejects modifications if the session has already been submitted.
    """
    if request.method == "OPTIONS":
        return "", 200

    try:
        data = request.get_json(silent=True) or {}
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT session_id, question_ids, option_orders, user_answers, is_submitted, client_id
            FROM practice_sessions
            WHERE session_id = ?;
        """, (session_id,))
        session = cursor.fetchone()

        if not session:
            conn.close()
            return jsonify({
                "status": "error",
                "message": "Practice session not found."
            }), 404

        # Validate session ownership
        ok, err_resp, status_code = check_session_ownership(session)
        if not ok:
            conn.close()
            return err_resp, status_code

        if bool(session["is_submitted"]):
            conn.close()
            return jsonify({
                "status": "error",
                "message": "Cannot modify answers for an already-submitted test."
            }), 403

        question_ids = set(json.loads(session["question_ids"]))
        option_orders = json.loads(session["option_orders"])
        existing_answers = json.loads(session["user_answers"] or "{}")

        # Support single answer {question_id, option_id} or batch {answers: {q_id: opt_id}}
        incoming_answers = {}
        if "question_id" in data:
            incoming_answers[str(data["question_id"])] = data.get("option_id")
        elif "answers" in data and isinstance(data["answers"], dict):
            incoming_answers = {str(k): v for k, v in data["answers"].items()}

        # Validate incoming answers
        for q_str, opt_val in incoming_answers.items():
            try:
                q_id = int(q_str)
            except ValueError:
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": f"Invalid question ID format: {q_str}"
                }), 400

            if q_id not in question_ids:
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": f"Question {q_id} does not belong to this practice session."
                }), 400

            if opt_val is not None and opt_val != "" and opt_val != 0:
                try:
                    opt_id = int(opt_val)
                except ValueError:
                    conn.close()
                    return jsonify({
                        "status": "error",
                        "message": f"Invalid option ID format: {opt_val}"
                    }), 400

                allowed_opts = option_orders.get(str(q_id), [])
                if opt_id not in allowed_opts:
                    conn.close()
                    return jsonify({
                        "status": "error",
                        "message": f"Option {opt_id} is not a valid choice for question {q_id}."
                    }), 400

                existing_answers[str(q_id)] = opt_id
            else:
                # Option was deselected / cleared
                existing_answers.pop(str(q_id), None)

        cursor.execute("""
            UPDATE practice_sessions
            SET user_answers = ?
            WHERE session_id = ?;
        """, (json.dumps(existing_answers), session_id))
        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "session_id": session_id,
            "saved_answers_count": len(existing_answers),
            "user_answers": existing_answers
        }), 200

    except Exception:
        return jsonify({
            "status": "error",
            "message": "An error occurred while saving answers."
        }), 500


@app.route("/api/practice/sessions/<session_id>/submit", methods=["POST", "OPTIONS"])
def submit_practice_session(session_id):
    """
    Submits a practice test for final server-side grading.
    Validates answers, grades against database answer keys, calculates score & counts,
    and locks the session against further modification.
    """
    if request.method == "OPTIONS":
        return "", 200

    try:
        data = request.get_json(silent=True) or {}
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT session_id, selected_weeks, test_type, question_ids, option_orders,
                   user_answers, is_submitted, score, total_marks,
                   correct_count, incorrect_count, unanswered_count, client_id
            FROM practice_sessions
            WHERE session_id = ?;
        """, (session_id,))
        session = cursor.fetchone()

        if not session:
            conn.close()
            return jsonify({
                "status": "error",
                "message": "Practice session not found."
            }), 404

        # Validate session ownership
        ok, err_resp, status_code = check_session_ownership(session)
        if not ok:
            conn.close()
            return err_resp, status_code

        if bool(session["is_submitted"]):
            conn.close()
            selected_weeks = json.loads(session["selected_weeks"])
            is_single_week = (len(selected_weeks) == 1)
            score = float(session["score"] or 0.0)
            total_marks = float(session["total_marks"] or 1.0)
            percentage = round((score / total_marks * 100), 1) if total_marks > 0 else 0.0
            is_mastered = (percentage >= 75.0) and is_single_week
            res_dict = {
                "id": session_id,
                "session_id": session_id,
                "status": "submitted",
                "test_type": session["test_type"],
                "selected_weeks": selected_weeks,
                "score": score,
                "total_marks": total_marks,
                "percentage": percentage,
                "correct_count": int(session["correct_count"] or 0),
                "incorrect_count": int(session["incorrect_count"] or 0),
                "unanswered_count": int(session["unanswered_count"] or 0),
                "is_single_week": is_single_week,
                "is_mastered": is_mastered
            }
            return jsonify({
                "status": "success",
                "message": "This practice test has already been submitted.",
                "result": res_dict,
                **res_dict
            }), 200

        question_ids = json.loads(session["question_ids"])
        option_orders = json.loads(session["option_orders"])
        user_answers = json.loads(session["user_answers"] or "{}")

        # Merge optional final_answers if provided in submit payload
        final_answers = data.get("final_answers") or data.get("answers")
        if isinstance(final_answers, dict):
            for q_str, opt_val in final_answers.items():
                try:
                    q_id = int(q_str)
                    if q_id in question_ids and opt_val is not None:
                        opt_id = int(opt_val)
                        if opt_id in option_orders.get(str(q_id), []):
                            user_answers[str(q_id)] = opt_id
                except (ValueError, TypeError):
                    pass

        # Server-side grading
        q_placeholders = ",".join("?" for _ in question_ids)
        cursor.execute(f"""
            SELECT id, marks
            FROM questions
            WHERE id IN ({q_placeholders});
        """, question_ids)
        question_marks = {r["id"]: float(r["marks"]) for r in cursor.fetchall()}

        cursor.execute(f"""
            SELECT id, question_id
            FROM options
            WHERE question_id IN ({q_placeholders}) AND is_correct = 1;
        """, question_ids)
        correct_options = {r["question_id"]: r["id"] for r in cursor.fetchall()}

        correct_count = 0
        incorrect_count = 0
        unanswered_count = 0
        score = 0.0
        total_marks = 0.0

        for q_id in question_ids:
            marks = question_marks.get(q_id, 1.0)
            total_marks += marks
            correct_opt_id = correct_options.get(q_id)
            user_opt_id = user_answers.get(str(q_id))

            if user_opt_id is None:
                unanswered_count += 1
            elif user_opt_id == correct_opt_id:
                correct_count += 1
                score += marks
            else:
                incorrect_count += 1

        percentage = round((score / total_marks * 100), 1) if total_marks > 0 else 0.0

        # Update database transactionally
        cursor.execute("""
            UPDATE practice_sessions
            SET is_submitted = 1,
                submitted_at = CURRENT_TIMESTAMP,
                user_answers = ?,
                score = ?,
                total_marks = ?,
                correct_count = ?,
                incorrect_count = ?,
                unanswered_count = ?
            WHERE session_id = ? AND is_submitted = 0;
        """, (
            json.dumps(user_answers),
            score,
            total_marks,
            correct_count,
            incorrect_count,
            unanswered_count,
            session_id
        ))
        conn.commit()
        conn.close()

        selected_weeks = json.loads(session["selected_weeks"])
        is_single_week = (len(selected_weeks) == 1)
        is_mastered = (percentage >= 75.0) and is_single_week

        result_dict = {
            "id": session_id,
            "session_id": session_id,
            "status": "submitted",
            "test_type": session["test_type"],
            "selected_weeks": selected_weeks,
            "total_questions": len(question_ids),
            "total_marks": total_marks,
            "score": score,
            "percentage": percentage,
            "correct_count": correct_count,
            "incorrect_count": incorrect_count,
            "unanswered_count": unanswered_count,
            "is_single_week": is_single_week,
            "is_mastered": is_mastered,
            "mastery_info": {
                "is_single_week": is_single_week,
                "week_number": selected_weeks[0] if is_single_week else None,
                "passed_mastery_threshold": is_mastered
            }
        }

        return jsonify({
            "status": "success",
            "result": result_dict,
            **result_dict
        }), 200

    except Exception:
        return jsonify({
            "status": "error",
            "message": "An error occurred while submitting the test."
        }), 500


@app.route("/api/practice/sessions/<session_id>/results", methods=["GET"])
def get_practice_results(session_id):
    """
    Retrieves full question-by-question review and grading results for a submitted test.
    Exposes verified answers only after test has been submitted.
    Includes explicit notice regarding provisional scoring baseline.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT session_id, created_at, submitted_at, selected_weeks, test_type,
                   question_ids, option_orders, user_answers, is_submitted,
                   score, total_marks, correct_count, incorrect_count, unanswered_count, client_id
            FROM practice_sessions
            WHERE session_id = ?;
        """, (session_id,))
        session = cursor.fetchone()

        if not session:
            conn.close()
            return jsonify({
                "status": "error",
                "message": "Practice session not found."
            }), 404

        # Validate session ownership
        ok, err_resp, status_code = check_session_ownership(session)
        if not ok:
            conn.close()
            return err_resp, status_code

        if not bool(session["is_submitted"]):
            conn.close()
            return jsonify({
                "status": "error",
                "message": "Practice test has not been submitted yet."
            }), 400

        question_ids = json.loads(session["question_ids"])
        option_orders = json.loads(session["option_orders"])
        user_answers = json.loads(session["user_answers"] or "{}")
        selected_weeks = json.loads(session["selected_weeks"])

        q_placeholders = ",".join("?" for _ in question_ids)
        cursor.execute(f"""
            SELECT id, week_number, question_number, question_order, question_text, marks
            FROM questions
            WHERE id IN ({q_placeholders});
        """, question_ids)
        questions_map = {r["id"]: dict(r) for r in cursor.fetchall()}

        cursor.execute(f"""
            SELECT id, question_id, option_letter, option_text, is_correct
            FROM options
            WHERE question_id IN ({q_placeholders});
        """, question_ids)
        options_map = {r["id"]: dict(r) for r in cursor.fetchall()}
        conn.close()

        score = float(session["score"] or 0.0)
        total_marks = float(session["total_marks"] or 0.0)
        percentage = round((score / total_marks * 100), 1) if total_marks > 0 else 0.0
        is_single_week = (len(selected_weeks) == 1)

        review_questions = []
        for q_idx, q_id in enumerate(question_ids):
            if q_id not in questions_map:
                continue
            q_info = questions_map[q_id]
            stored_opt_ids = option_orders.get(str(q_id), [])
            user_opt_id = user_answers.get(str(q_id))

            opts_review = []
            correct_opt_id = None
            for idx, opt_id in enumerate(stored_opt_ids):
                if opt_id in options_map:
                    opt_data = options_map[opt_id]
                    is_corr = bool(opt_data["is_correct"])
                    if is_corr:
                        correct_opt_id = opt_id
                    opts_review.append({
                        "id": opt_id,
                        "option_letter": chr(ord('a') + idx),
                        "option_text": opt_data["option_text"],
                        "is_correct": 1 if is_corr else 0,
                        "is_user_selected": (opt_id == user_opt_id)
                    })

            is_correct = (user_opt_id is not None and user_opt_id == correct_opt_id)
            earned_marks = float(q_info["marks"]) if is_correct else 0.0

            review_questions.append({
                "id": q_id,
                "test_question_number": q_idx + 1,
                "week_number": q_info["week_number"],
                "question_text": q_info["question_text"],
                "marks": float(q_info["marks"]),
                "earned_marks": earned_marks,
                "user_selected_option_id": user_opt_id,
                "correct_option_id": correct_opt_id,
                "is_correct": is_correct,
                "is_unanswered": (user_opt_id is None),
                "options": opts_review
            })

        is_mastered = (percentage >= 75.0) and is_single_week

        summary_dict = {
            "session_id": session["session_id"],
            "created_at": session["created_at"],
            "submitted_at": session["submitted_at"],
            "test_type": session["test_type"],
            "selected_weeks": selected_weeks,
            "total_questions": len(review_questions),
            "score": score,
            "score_earned": score,
            "total_marks": total_marks,
            "percentage": percentage,
            "correct_count": int(session["correct_count"] or 0),
            "incorrect_count": int(session["incorrect_count"] or 0),
            "unanswered_count": int(session["unanswered_count"] or 0),
            "is_single_week": is_single_week,
            "is_mastered": is_mastered,
            "marks_provisional_note": "Scoring uses marks=1.0 per question as a provisional baseline since source assignment PDFs do not confirm official marks scheme.",
            "mastery_info": {
                "is_single_week": is_single_week,
                "week_number": selected_weeks[0] if is_single_week else None,
                "passed_mastery_threshold": is_mastered
            }
        }

        return jsonify({
            "status": "success",
            "summary": summary_dict,
            **summary_dict,
            "questions": review_questions
        }), 200

    except Exception:
        return jsonify({
            "status": "error",
            "message": "An error occurred while retrieving test results."
        }), 500


@app.route("/api/practice/attempts", methods=["GET"])
def get_practice_attempts():
    """
    Retrieves previous submitted practice attempts.
    """
    try:
        client_id = get_request_client_id()
        if not client_id:
            return jsonify({
                "status": "error",
                "message": "client_id is required to retrieve attempt history."
            }), 400

        if not is_valid_client_id(client_id):
            return jsonify({
                "status": "error",
                "message": "Invalid client_id format."
            }), 400

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT session_id, created_at, submitted_at, selected_weeks, test_type,
                   score, total_marks, correct_count, incorrect_count, unanswered_count
            FROM practice_sessions
            WHERE is_submitted = 1 AND client_id = ?
            ORDER BY submitted_at DESC
            LIMIT 50;
        """, (client_id,))

        rows = cursor.fetchall()
        conn.close()

        attempts = []
        for r in rows:
            sc = float(r["score"] or 0.0)
            tm = float(r["total_marks"] or 0.0)
            pct = round((sc / tm * 100), 1) if tm > 0 else 0.0
            attempts.append({
                "session_id": r["session_id"],
                "created_at": r["created_at"],
                "submitted_at": r["submitted_at"],
                "selected_weeks": json.loads(r["selected_weeks"]),
                "test_type": r["test_type"],
                "score": sc,
                "total_marks": tm,
                "percentage": pct,
                "correct_count": int(r["correct_count"] or 0),
                "incorrect_count": int(r["incorrect_count"] or 0),
                "unanswered_count": int(r["unanswered_count"] or 0)
            })

        return jsonify({
            "status": "success",
            "count": len(attempts),
            "attempts": attempts
        }), 200

    except Exception:
        return jsonify({
            "status": "error",
            "message": "An error occurred while retrieving attempts."
        }), 500


# --- Unknown API Catch-All (Returns JSON 404 instead of static file handler) ---

@app.route("/api/<path:unmatched>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def api_not_found(unmatched):
    """
    Catch-all endpoint for unknown /api/* requests.
    Returns JSON 404 instead of falling through to static file serving.
    """
    if request.method == "OPTIONS":
        return "", 200
    return jsonify({
        "status": "error",
        "message": f"API endpoint '/api/{unmatched}' not found."
    }), 404


if __name__ == "__main__":
    print(f"Starting NPTEL Practice Hub on http://127.0.0.1:5000 (Backend: {BACKEND_DIR})")
    app.run(host="127.0.0.1", port=5000, debug=False)
