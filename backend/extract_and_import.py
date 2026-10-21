"""
NPTEL Practice Hub - PDF Extraction and Database Importer
Extracts questions, options, and verified bold answers from the 12 Conservation Geography
assignment solution PDFs and imports them into backend/instance/nptel_hub.db transactionally.
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Ensure backend directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pdfplumber
from database import get_db_connection

DOWNLOADS_DIR = Path(r"C:\Users\vishn\Downloads")

PDF_SPECS = [
    (1, DOWNLOADS_DIR / "Conservation Geography Week 1 Solutions.pdf"),
    (2, DOWNLOADS_DIR / "Conservation Geography Week 2 Solutions.pdf"),
    (3, DOWNLOADS_DIR / "Conservation Geography Week 3 Solutions.docx.pdf"),
    (4, DOWNLOADS_DIR / "Conservation Geography Week 4 Solutions.pdf"),
    (5, DOWNLOADS_DIR / "Conservation Geography Week 5 Solutions.pdf"),
    (6, DOWNLOADS_DIR / "Conservation Geography Week 6 Solutions.pdf"),
    (7, DOWNLOADS_DIR / "Conservation Geography Week 7 Solutions.pdf"),
    (8, DOWNLOADS_DIR / "Conservation Geography Week 8 Solutions.pdf"),
    (9, DOWNLOADS_DIR / "Conservation Geography Week 9 Solutions.pdf"),
    (10, DOWNLOADS_DIR / "Conservation Geography Week 10 Solutions.pdf"),
    (11, DOWNLOADS_DIR / "Conservation Geography Week 11 Solutions.pdf"),
    (12, DOWNLOADS_DIR / "Conservation Geography Week 12 Solutions.pdf"),
]

Q_START_REGEX = re.compile(r"^(\d{1,2})[\.\s]+(.*)$")
OPT_START_REGEX = re.compile(r"^(?:\(([a-dA-D1-4])\)|([a-dA-D])\.)\s*(.*)$")


def clean_text(text: str) -> str:
    """Normalizes excessive whitespace while preserving unicode symbols."""
    return re.sub(r"[ \t]+", " ", text).strip()


def is_word_bold(w: Dict[str, Any]) -> bool:
    """Checks if a word dictionary from pdfplumber has a bold font."""
    fontname = w.get("fontname", "").lower()
    return "bold" in fontname or "black" in fontname or "heavy" in fontname


def extract_week_data(week_num: int, pdf_path: Path) -> Dict[str, Any]:
    """
    Extracts week title, questions, options, and bold status from a PDF.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file for Week {week_num} not found at: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        all_lines = []
        raw_header_lines = []

        for p_idx, page in enumerate(pdf.pages):
            words = page.extract_words(extra_attrs=["fontname", "size"])
            # Group into visual lines based on vertical proximity
            lines_dict = {}
            for w in words:
                found_top = None
                for top in lines_dict:
                    if abs(w["top"] - top) < 3.5:
                        found_top = top
                        break
                if found_top is None:
                    found_top = w["top"]
                    lines_dict[found_top] = []
                lines_dict[found_top].append(w)

            sorted_tops = sorted(lines_dict.keys())
            for top in sorted_tops:
                line_words = sorted(lines_dict[top], key=lambda x: x["x0"])
                line_text = " ".join(w["text"] for w in line_words).strip()
                if not line_text:
                    continue
                all_lines.append({
                    "page": p_idx + 1,
                    "text": line_text,
                    "words": line_words,
                    "top": top
                })

    # Determine title from initial header lines
    for item in all_lines[:4]:
        t = item["text"]
        if "Conservation Geography" in t or "Assignment Solutions" in t:
            raw_header_lines.append(t)

    title = " - ".join(raw_header_lines) if raw_header_lines else f"Conservation Geography Week {week_num}"

    # Parse questions and options
    questions = []
    current_q = None
    current_opt = None

    for line_info in all_lines:
        text = line_info["text"]
        words = line_info["words"]
        page = line_info["page"]

        # Skip document title/header lines
        if "Conservation Geography" in text or "Assignment Solutions" in text:
            continue

        q_match = Q_START_REGEX.match(text)
        opt_match = OPT_START_REGEX.match(text)

        is_new_q = False
        if q_match and not opt_match:
            q_num = int(q_match.group(1))
            if 1 <= q_num <= 25:
                if current_q is None and q_num == 1:
                    is_new_q = True
                elif current_q and q_num == current_q["question_number"] + 1:
                    is_new_q = True

        if is_new_q:
            if current_q:
                questions.append(current_q)
            q_num = int(q_match.group(1))
            q_text = q_match.group(2).strip()
            current_q = {
                "question_number": q_num,
                "question_order": len(questions) + 1,
                "question_text": q_text,
                "marks": 1.0,  # Provisional schema default
                "page": page,
                "options": []
            }
            current_opt = None
            continue

        if current_q is not None:
            if opt_match:
                opt_letter = (opt_match.group(1) or opt_match.group(2)).lower()
                opt_text = opt_match.group(3).strip()

                bold_words = 0
                total_words = 0
                for idx, w in enumerate(words):
                    # Exclude the option identifier prefix from bold evaluation
                    if idx == 0 and (w["text"].startswith("(") or w["text"].endswith(".")):
                        continue
                    if is_word_bold(w):
                        bold_words += 1
                    total_words += 1

                current_opt = {
                    "option_letter": opt_letter,
                    "option_order": len(current_q["options"]) + 1,
                    "option_text": opt_text,
                    "bold_words": bold_words,
                    "total_words": total_words,
                    "page": page
                }
                current_q["options"].append(current_opt)
            else:
                if current_opt is not None:
                    current_opt["option_text"] += " " + text
                    for w in words:
                        if is_word_bold(w):
                            current_opt["bold_words"] += 1
                        current_opt["total_words"] += 1
                else:
                    current_q["question_text"] += " " + text

    if current_q:
        questions.append(current_q)

    # Process options, clean text, and evaluate verification
    for q in questions:
        q["question_text"] = clean_text(q["question_text"])
        correct_letters = []

        for opt in q["options"]:
            opt["option_text"] = clean_text(opt["option_text"])
            # Option is considered bold if at least 50% of content words are bold
            if opt["total_words"] > 0 and (opt["bold_words"] / opt["total_words"] >= 0.5):
                opt["is_correct"] = 1
                correct_letters.append(opt["option_letter"])
            else:
                opt["is_correct"] = 0

        # Strict verification criteria
        if len(correct_letters) == 1 and len(q["options"]) >= 2 and q["question_text"]:
            q["is_verified"] = 1
            q["flag_reason"] = None
        else:
            q["is_verified"] = 0
            if len(correct_letters) == 0:
                q["flag_reason"] = "No bold answer identified in source PDF"
            elif len(correct_letters) > 1:
                q["flag_reason"] = f"Ambiguous bold formatting: multiple bold options ({correct_letters})"
            else:
                q["flag_reason"] = "Invalid question or option structure"

    return {
        "week_number": week_num,
        "title": title,
        "total_questions": len(questions),
        "questions": questions
    }


def import_all_weeks(db_path: Path = None) -> Dict[str, Any]:
    """
    Safely and transactionally imports all 12 weeks of questions into SQLite.
    Preserves database integrity and is safe to run repeatedly.
    """
    conn = get_db_connection(db_path)
    audit_summary = []

    try:
        with conn:
            cursor = conn.cursor()

            for week_num, pdf_path in PDF_SPECS:
                week_data = extract_week_data(week_num, pdf_path)

                # Upsert week metadata
                cursor.execute(
                    """
                    INSERT INTO weeks (week_number, title, total_questions)
                    VALUES (?, ?, ?)
                    ON CONFLICT(week_number) DO UPDATE SET
                        title = excluded.title,
                        total_questions = excluded.total_questions;
                    """,
                    (week_data["week_number"], week_data["title"], week_data["total_questions"])
                )

                # Delete previous questions for this week to allow clean re-import
                # (CASCADE constraint automatically deletes dependent options)
                cursor.execute("DELETE FROM questions WHERE week_number = ?;", (week_num,))

                verified_count = 0
                unverified_count = 0

                for q in week_data["questions"]:
                    if q["is_verified"] == 1:
                        verified_count += 1
                    else:
                        unverified_count += 1

                    cursor.execute(
                        """
                        INSERT INTO questions (
                            week_number, question_number, question_order,
                            question_text, marks, is_verified, flag_reason
                        ) VALUES (?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            week_num,
                            q["question_number"],
                            q["question_order"],
                            q["question_text"],
                            q["marks"],
                            q["is_verified"],
                            q["flag_reason"]
                        )
                    )
                    question_id = cursor.lastrowid

                    for opt in q["options"]:
                        cursor.execute(
                            """
                            INSERT INTO options (
                                question_id, option_letter, option_order,
                                option_text, is_correct
                            ) VALUES (?, ?, ?, ?, ?);
                            """,
                            (
                                question_id,
                                opt["option_letter"],
                                opt["option_order"],
                                opt["option_text"],
                                opt["is_correct"]
                            )
                        )

                audit_summary.append({
                    "week_number": week_num,
                    "title": week_data["title"],
                    "total_questions": week_data["total_questions"],
                    "verified": verified_count,
                    "unverified": unverified_count
                })

        print("Transactional import completed successfully.")
        return {"status": "SUCCESS", "weeks": audit_summary}

    except Exception as e:
        print(f"Error during import: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("Starting extraction and transactional import for Weeks 1-12...")
    result = import_all_weeks()
    print("\nImport Summary:")
    for w in result["weeks"]:
        print(f"  Week {w['week_number']:2d}: {w['total_questions']} questions (Verified: {w['verified']}, Unverified: {w['unverified']}) - {w['title']}")
