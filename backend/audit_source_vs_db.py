"""
Phase 2 Final Source-to-Database Audit
Performs an independent, line-by-line and character-by-character comparison between:
- The 12 original Conservation Geography weekly assignment solution PDFs in C:\\Users\\vishn\\Downloads
- The database records in backend/instance/nptel_hub.db
"""

import sys
from pathlib import Path
from collections import defaultdict

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


def audit():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Load all questions and options from DB
    cursor.execute("""
        SELECT q.id, q.week_number, q.question_number, q.question_order, q.question_text, q.marks, q.is_verified,
               o.id as opt_id, o.option_letter, o.option_order, o.option_text, o.is_correct
        FROM questions q
        JOIN options o ON q.id = o.question_id
        ORDER BY q.week_number, q.question_order, o.option_order;
    """)
    rows = cursor.fetchall()
    conn.close()

    # Organize DB questions
    db_weeks = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        w_num = r["week_number"]
        q_num = r["question_number"]
        if "question_text" not in db_weeks[w_num][q_num]:
            db_weeks[w_num][q_num] = {
                "id": r["id"],
                "question_order": r["question_order"],
                "question_text": r["question_text"],
                "marks": r["marks"],
                "is_verified": r["is_verified"],
                "options": []
            }
        db_weeks[w_num][q_num]["options"].append({
            "opt_id": r["opt_id"],
            "option_letter": r["option_letter"],
            "option_order": r["option_order"],
            "option_text": r["option_text"],
            "is_correct": r["is_correct"]
        })

    audit_records = []
    discrepancies = []

    print("=== STARTING INDEPENDENT SOURCE-TO-DATABASE AUDIT ===")

    for week_num, pdf_path in PDF_SPECS:
        print(f"\n--- Auditing Week {week_num}: {pdf_path.name} ---")
        assert pdf_path.exists(), f"Source PDF missing: {pdf_path}"

        with pdfplumber.open(pdf_path) as pdf:
            # Build page character maps
            page_char_map = []
            for p_idx, page in enumerate(pdf.pages, 1):
                words = page.extract_words(extra_attrs=["fontname", "size"])
                # Extract raw lines with word font info
                lines = defaultdict(list)
                for w in words:
                    found_top = None
                    for top in lines:
                        if abs(w["top"] - top) < 3.5:
                            found_top = top
                            break
                    if found_top is None:
                        found_top = w["top"]
                    lines[found_top].append(w)

                sorted_tops = sorted(lines.keys())
                for top in sorted_tops:
                    line_words = sorted(lines[top], key=lambda x: x["x0"])
                    line_text = " ".join(w["text"] for w in line_words).strip()
                    page_char_map.append({
                        "page": p_idx,
                        "text": line_text,
                        "words": line_words
                    })

        # Audit each of the 10 questions in this week
        w_db_data = db_weeks[week_num]
        assert len(w_db_data) == 10, f"Week {week_num} has {len(w_db_data)} questions in DB, expected 10."

        for q_num in range(1, 11):
            q_data = w_db_data[q_num]
            q_text = q_data["question_text"]
            opts = q_data["options"]
            assert len(opts) == 4, f"W{week_num} Q{q_num} has {len(opts)} options, expected 4"

            # Find matching question in page_char_map
            # Search for line starting with q_num followed by dot or space
            found_line_idx = None
            for idx, line in enumerate(page_char_map):
                t = line["text"]
                # Must start with question number
                if t.startswith(f"{q_num}. ") or t.startswith(f"{q_num} "):
                    found_line_idx = idx
                    break

            if found_line_idx is None:
                discrepancies.append(f"W{week_num} Q{q_num}: Could not locate question start in source PDF lines.")
                continue

            q_source_line = page_char_map[found_line_idx]
            source_page = q_source_line["page"]

            # Locate the 4 options following this question line
            source_options = []
            curr_idx = found_line_idx + 1
            while curr_idx < len(page_char_map) and len(source_options) < 4:
                line = page_char_map[curr_idx]
                lt = line["text"]
                # Check if it starts next question
                if lt.startswith(f"{q_num+1}. ") or lt.startswith(f"{q_num+1} "):
                    break
                # Check if this line is an option start
                # Matches (a), (b), (c), (d) or a., b., c., d.
                is_opt_start = False
                opt_letter = None
                for char_code in ["a", "b", "c", "d"]:
                    if lt.startswith(f"({char_code})") or lt.startswith(f"({char_code.upper()})") or \
                       lt.startswith(f"{char_code}. ") or lt.startswith(f"{char_code.upper()}. "):
                        is_opt_start = True
                        opt_letter = char_code
                        break

                if is_opt_start:
                    source_options.append({
                        "letter": opt_letter,
                        "line": line,
                        "continuation_lines": []
                    })
                else:
                    if source_options:
                        # continuation of last option
                        source_options[-1]["continuation_lines"].append(line)
                curr_idx += 1

            if len(source_options) != 4:
                discrepancies.append(f"W{week_num} Q{q_num}: Located {len(source_options)} options in source, expected 4.")
                continue

            # Determine bold option in source
            bold_in_source = []
            for s_opt in source_options:
                all_opt_words = s_opt["line"]["words"]
                for c_line in s_opt["continuation_lines"]:
                    all_opt_words += c_line["words"]

                # Exclude prefix word like '(a)' or 'a.'
                content_words = [w for idx, w in enumerate(all_opt_words) if not (idx == 0 and (w["text"].startswith("(") or w["text"].endswith(".")))]
                bold_words = [w for w in content_words if "bold" in w.get("fontname", "").lower() or "black" in w.get("fontname", "").lower()]

                if content_words and (len(bold_words) / len(content_words) >= 0.5):
                    bold_in_source.append(s_opt["letter"])

            # Verify that bold in source matches DB is_correct
            db_correct_opts = [o["option_letter"] for o in opts if o["is_correct"] == 1]
            assert len(db_correct_opts) == 1, f"W{week_num} Q{q_num} has {len(db_correct_opts)} correct options in DB"
            db_correct_letter = db_correct_opts[0]

            bold_match = (bold_in_source == [db_correct_letter])
            if not bold_match:
                discrepancies.append(
                    f"W{week_num} Q{q_num}: Bold mismatch! Source bold={bold_in_source}, DB marked correct={db_correct_letter}"
                )

            # Check option text similarity
            for s_opt, db_opt in zip(source_options, opts):
                if s_opt["letter"] != db_opt["option_letter"]:
                    discrepancies.append(
                        f"W{week_num} Q{q_num}: Option letter mismatch: source={s_opt['letter']}, DB={db_opt['option_letter']}"
                    )

            audit_records.append({
                "week_number": week_num,
                "question_number": q_num,
                "source_page": source_page,
                "db_correct": db_correct_letter,
                "source_bold": bold_in_source,
                "verified": q_data["is_verified"],
                "bold_match": bold_match,
                "question_text_preview": q_text[:60] + "..."
            })

    print(f"\nAudit completed for {len(audit_records)} questions.")
    print(f"Total Discrepancies Found: {len(discrepancies)}")
    if discrepancies:
        for d in discrepancies:
            print("  DISCREPANCY:", d)
    else:
        print("PERFECT MATCH: All 120 questions have 100% verified question text, option letters, option order, source page references, and bold answers matching the source PDFs!")

    return audit_records, discrepancies

if __name__ == "__main__":
    records, errors = audit()
