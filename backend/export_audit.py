"""
Export all 120 extracted questions to JSON for complete verification and auditing.
"""

import json
import re
from pathlib import Path
import pdfplumber

DOWNLOADS_DIR = Path(r"C:\Users\vishn\Downloads")

pdf_files = [
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

# Clean up unicode quotes and dashes that might be converted or preserved
def clean_text(text):
    # Normalize excessive spaces while keeping meaningful structure
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text

def is_word_bold(w):
    fontname = w.get("fontname", "").lower()
    return "bold" in fontname or "black" in fontname or "heavy" in fontname

all_extracted_weeks = []

for week_num, path in pdf_files:
    with pdfplumber.open(path) as pdf:
        all_lines = []
        for p_idx, page in enumerate(pdf.pages):
            words = page.extract_words(extra_attrs=["fontname", "size"])
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
                all_lines.append({
                    "page": p_idx + 1,
                    "text": line_text,
                    "words": line_words,
                    "top": top
                })

    week_title = f"Week {week_num}"
    questions = []
    current_q = None
    current_opt = None

    Q_START_REGEX = re.compile(r"^(\d{1,2})[\.\s]+(.*)$")
    OPT_START_REGEX = re.compile(r"^(?:\(([a-dA-D1-4])\)|([a-dA-D])\.)\s*(.*)$")

    for line_info in all_lines:
        text = line_info["text"]
        words = line_info["words"]
        page = line_info["page"]

        if "Conservation Geography" in text or "Assignment Solutions" in text:
            # Check if this has week title info
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
                "marks": 1.0,  # Default fallback; checked for explicit marks
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

    # Clean text and calculate correct option
    for q in questions:
        q["question_text"] = clean_text(q["question_text"])
        correct_letters = []
        for opt in q["options"]:
            opt["option_text"] = clean_text(opt["option_text"])
            if opt["total_words"] > 0 and (opt["bold_words"] / opt["total_words"] >= 0.5):
                opt["is_correct"] = 1
                correct_letters.append(opt["option_letter"])
            else:
                opt["is_correct"] = 0

        # Verification check
        if len(correct_letters) == 1 and len(q["options"]) >= 2 and q["question_text"]:
            q["is_verified"] = 1
            q["flag_reason"] = None
        else:
            q["is_verified"] = 0
            if len(correct_letters) == 0:
                q["flag_reason"] = "No bold answer identified in PDF"
            elif len(correct_letters) > 1:
                q["flag_reason"] = f"Multiple bold answers identified: {correct_letters}"
            else:
                q["flag_reason"] = "Invalid question or option structure"

    all_extracted_weeks.append({
        "week_number": week_num,
        "title": f"Week {week_num}: Assignment Solutions",
        "total_questions": len(questions),
        "questions": questions
    })

output_path = Path("backend/extracted_questions_audit.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(all_extracted_weeks, f, indent=2, ensure_ascii=False)

print(f"Exported audit data for {len(all_extracted_weeks)} weeks to {output_path}")
