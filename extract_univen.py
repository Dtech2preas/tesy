import pdfplumber
import re
import json

def clean_str(s):
    if not s:
        return ""
    s = str(s).replace('\n', ' ')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def parse_subjects(reqs_str):
    """
    Extract specific subjects from requirements text.
    Exclude general NSC requirements.
    Extract Subject, Level, Percentage.
    Split 'or' into individual subjects.
    """
    # 1. Remove the NSC X part
    clean_reqs = re.sub(r'(?:NSC|NCS)\s*\d+\s*\+?', '', reqs_str, flags=re.IGNORECASE)

    # 2. Extract base level/percentage if there's a general statement
    base_level = "Unspecified"
    base_pct = "Unspecified"

    level_match = re.search(r'level\s+(?:of\s+)?(\d)', clean_reqs, re.IGNORECASE)
    pct_match = re.search(r'(\d{2}\s*-\s*\d{2}%|\d{2}%)', clean_reqs)

    if level_match:
        base_level = level_match.group(1)
    if pct_match:
        base_pct = pct_match.group(1).replace(' ', '')

    # Standardize 'or' and 'and' for splitting
    work_str = clean_reqs
    work_str = re.sub(r'\s+or\s+', ' | ', work_str, flags=re.IGNORECASE)
    work_str = re.sub(r'\s+and\s+', ' | ', work_str, flags=re.IGNORECASE)
    work_str = re.sub(r',', ' | ', work_str)
    work_str = re.sub(r'\.', ' | ', work_str)
    work_str = re.sub(r':', ' | ', work_str)
    work_str = re.sub(r';', ' | ', work_str)

    subjects = []
    parts = work_str.split('|')

    # List of known subjects from the prospectus
    known_subjects = [
        "Mathematics", "Physical Science", "Physical Sciences", "Life Sciences", "English",
        "Accounting", "Business Studies", "Economics", "Information Technology", "Computer Studies",
        "Mathematical Literacy", "History", "Geography", "Agricultural Sciences", "Sepedi", "Tshivenda",
        "Xitsonga", "African Languages"
    ]

    found_subjects = set()

    for part in parts:
        part = clean_str(part)
        for ks in known_subjects:
            # check if known subject is in this chunk
            if ks.lower() in part.lower() and ks not in found_subjects:

                # Check for localized percentages like 'English (50%)'
                local_pct = base_pct
                local_pct_match = re.search(r'(\d{2}\s*-\s*\d{2}%|\d{2}%)', part)
                if local_pct_match:
                    local_pct = local_pct_match.group(1).replace(' ', '')

                local_level = base_level
                local_level_match = re.search(r'level\s+(\d)', part, re.IGNORECASE)
                if local_level_match:
                    local_level = local_level_match.group(1)

                subjects.append({
                    "subject": ks,
                    "level": local_level,
                    "percentage": local_pct
                })
                found_subjects.add(ks)

    # Normalize known duplicate subjects like "Physical Science" and "Physical Sciences"
    normalized_subjects = []
    seen = set()
    for s in subjects:
        subj = s["subject"]
        if subj == "Physical Science":
            subj = "Physical Sciences"
        if subj not in seen:
            s["subject"] = subj
            normalized_subjects.append(s)
            seen.add(subj)

    return normalized_subjects

def extract_data(pdf_path):
    faculty_data = {}
    current_faculty = None

    with pdfplumber.open(pdf_path) as pdf:
        num_pages = len(pdf.pages)
        for i in range(12, num_pages): # pages with tables
            page = pdf.pages[i]

            # Extract text to find faculty headers
            text = page.extract_text()
            if text:
                for line in text.split('\n'):
                    if line.startswith("Faculty of"):
                        fac_name = clean_str(line.replace("Programmes", ""))
                        if fac_name and len(fac_name) > 10:
                            current_faculty = fac_name

            if not current_faculty:
                continue

            if current_faculty not in faculty_data:
                faculty_data[current_faculty] = []

            # Tables extraction
            # We use explicit settings to avoid merging columns incorrectly
            table_settings = {
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "intersection_y_tolerance": 15
            }
            tables = page.extract_tables() # default strategy usually works better for univen.pdf

            for table in tables:
                for row in table:
                    clean_row = [clean_str(c) for c in row if clean_str(c)]
                    if len(clean_row) >= 3:
                        text_row = " ".join(clean_row).lower()
                        # Detect if row is a programme row
                        if "year" in text_row:
                            # 1. Identify Duration
                            dur_idx = -1
                            for idx, c in enumerate(clean_row):
                                if "year" in c.lower():
                                    dur_idx = idx
                                    break

                            duration = re.sub(r'[^\d]', '', clean_row[dur_idx]) if dur_idx != -1 else ""

                            # 2. Identify Code
                            code_idx = -1
                            code = ""
                            for idx, c in enumerate(clean_row):
                                # code is usually all caps in parentheses
                                if '(' in c and ')' in c and any(char.isupper() for char in c) and len(c) < 15:
                                    code_idx = idx
                                    code = c.replace('(', '').replace(')', '').strip()
                                    break

                            # If code wasn't found by parens, maybe it's the 2nd column
                            if code_idx == -1 and len(clean_row) >= 4:
                                code_candidate = clean_row[1]
                                if len(code_candidate) < 10 and code_candidate.isupper():
                                    code = code_candidate
                                    code_idx = 1

                            # 3. Identify Programme Name
                            prog = clean_row[0]
                            if len(clean_row[0]) < 10 and len(clean_row) > 1 and "Bachelor" in clean_row[1]:
                                prog = clean_row[1]
                            elif code_idx > 0:
                                # Sometimes the text is split across the first two columns.
                                # Check if col 0 and 1 are the same or complement each other
                                if clean_row[0] == clean_row[1] or clean_row[1] in clean_row[0]:
                                    prog = clean_row[0]
                                elif clean_row[0] in clean_row[1]:
                                    prog = clean_row[1]
                                else:
                                    # It might be split like "Bachelor of Arts" "in something"
                                    # For safety just take the first col if it contains "Bachelor" or "BSc"
                                    if "Bachelor" in clean_row[0] or "BSc" in clean_row[0] or "Diploma" in clean_row[0]:
                                        prog = clean_row[0]
                                        # But let's append parts if it looks cut off
                                        if clean_row[0].endswith("in") and len(clean_row) > 1:
                                            prog += " " + clean_row[1]
                                    else:
                                        prog = clean_row[0]

                            # Strip code and other things from prog
                            prog = re.sub(r'\(\s*[A-Z]+\s*\)', '', prog).strip()
                            prog = re.sub(r'\(|\)', '', prog).strip()
                            # remove code if it happens to be at end of prog
                            if prog.endswith(code):
                                prog = prog[:-len(code)].strip()
                            # general clean
                            prog = clean_str(prog)

                            # 4. Identify Requirements
                            reqs = ""
                            start_req_idx = code_idx + 1 if code_idx != -1 else 1
                            end_req_idx = dur_idx if dur_idx != -1 else len(clean_row)

                            if start_req_idx < end_req_idx:
                                reqs = " ".join(clean_row[start_req_idx:end_req_idx])
                            else:
                                # Fallback, find the longest string containing NSC/NCS
                                for c in clean_row:
                                    if 'NSC' in c or 'NCS' in c:
                                        reqs = c
                                        break

                            if not reqs:
                                reqs = max(clean_row, key=len)

                            # Extract APS from requirements
                            aps_match = re.search(r'(?:NSC|NCS)\s*(\d{2})', reqs, re.IGNORECASE)
                            aps = aps_match.group(1) if aps_match else ""


                            # Build object
                            if prog and duration and code:
                                req_subjects = parse_subjects(reqs)
                                # Filter out any subjects that look like the course code
                                req_subjects = [s for s in req_subjects if not (s['subject'].endswith(')') or code in s['subject'])]

                                course_obj = {
                                    "course_name": prog,
                                    "course_code": code,
                                    "duration": duration,
                                    "aps": aps,
                                    "required_subjects": req_subjects
                                }
                                faculty_data[current_faculty].append(course_obj)

    # Dedup
    final_data = {}
    for fac in faculty_data:
        unique_progs = []
        seen_codes = set()
        for p in faculty_data[fac]:
            # Ensure no duplicates
            if p['course_code'] not in seen_codes:
                seen_codes.add(p['course_code'])
                unique_progs.append(p)
        if unique_progs:
            final_data[fac] = unique_progs

    return final_data

if __name__ == "__main__":
    data = extract_data('univen.pdf')
    with open("univen.json", "w") as f:
        json.dump(data, f, indent=4)
    print("Extraction complete.")
