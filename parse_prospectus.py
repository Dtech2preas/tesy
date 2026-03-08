import pdfplumber
import json
import re

def process_pdf(pdf_path):
    faculty_data = {}
    current_faculty = None

    def clean_subject_name(name):
        return name.replace('\n', ' ').strip()

    def extract_level(level_str):
        level_str = level_str.replace('\n', ' ').strip()
        if not level_str or level_str.lower() in ['n/a', '-', '', 'unspecified']:
            return None
        return level_str

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            lines = text.split('\n')
            for line in lines:
                if line.startswith("Faculty of ") or line.startswith("FACULTY OF "):
                    m = re.match(r'(Faculty of [A-Za-z\s,]+)(?:\s+\d+)?(?:\s+.*)?$', line, re.IGNORECASE)
                    if m:
                        faculty_name = m.group(1).strip().upper()
                        if "WEBSITE" not in faculty_name and "PLEASE CONSULT" not in faculty_name and "MINIMUM" not in faculty_name:
                            current_faculty = faculty_name
                            if current_faculty not in faculty_data:
                                faculty_data[current_faculty] = []
                            break

            if not current_faculty:
                continue

            tables = page.extract_tables()
            for table in tables:
                if not table or not table[0] or not table[0][0]:
                    continue

                if "Programmes" not in str(table[0][0]):
                    continue

                aps_idx = -1
                for r_idx, row in enumerate(table[:4]):
                    for c_idx, cell in enumerate(row):
                        if cell and "APS" in str(cell):
                            aps_idx = c_idx
                            break
                    if aps_idx != -1:
                        break

                if aps_idx == -1:
                    aps_idx = len(table[0]) - 1

                subject_cols = {}
                for r_idx in range(4):
                    if r_idx < len(table):
                        row = table[r_idx]
                        for c_idx in range(1, aps_idx):
                            if c_idx < len(row) and row[c_idx] and isinstance(row[c_idx], str):
                                text_val = row[c_idx].replace('\n', ' ').strip()
                                if text_val and text_val not in ["Achievement level", ""]:
                                    if c_idx not in subject_cols:
                                        subject_cols[c_idx] = text_val
                                    else:
                                        if len(text_val) > len(subject_cols[c_idx]):
                                            subject_cols[c_idx] = text_val

                for r_idx, row in enumerate(table):
                    if r_idx < 2:
                        continue

                    prog_cell = row[0]
                    if not prog_cell or not isinstance(prog_cell, str):
                        continue

                    prog_text = prog_cell.replace('\n', ' ').strip()
                    if ("Bachelor" in prog_text or "Diploma" in prog_text or "Certificate" in prog_text or "[x" in prog_text or "]" in prog_text) and not prog_text.startswith("Careers:") and not prog_text.startswith("Suggested") and not prog_text.startswith("Selection") and not prog_text.startswith("For advice") and not prog_text.startswith("This is") and not prog_text.startswith("Proposed"):

                        course_name = prog_text
                        duration = ""
                        m = re.search(r'\[(\d+)\s+years?\]', prog_text, re.IGNORECASE)
                        if m:
                            duration = m.group(1)
                            course_name = re.sub(r'\[\d+\s+years?\]', '', course_name, flags=re.IGNORECASE).strip()
                        else:
                            m2 = re.search(r'\[(\d+)\s+year\]', prog_text, re.IGNORECASE)
                            if m2:
                                duration = m2.group(1)
                                course_name = re.sub(r'\[\d+\s+year\]', '', course_name, flags=re.IGNORECASE).strip()

                        course_name = re.sub(r'\[Options?:.*\]', '', course_name).strip()
                        course_name = course_name.replace('\u0083', ',')

                        aps = ""
                        if aps_idx < len(row) and row[aps_idx]:
                            aps_raw = str(row[aps_idx]).replace('\n', ' ').strip()
                            m3 = re.search(r'^(\d+)', aps_raw)
                            if m3:
                                aps = m3.group(1)

                        # If aps is blank but it's on the next line (like Veterinary Nursing)
                        # We look ahead
                        if not aps and r_idx + 1 < len(table) and table[r_idx + 1][0] is None:
                            next_row = table[r_idx + 1]
                            if aps_idx < len(next_row) and next_row[aps_idx]:
                                aps_raw = str(next_row[aps_idx]).replace('\n', ' ').strip()
                                m3 = re.search(r'^(\d+)', aps_raw)
                                if m3:
                                    aps = m3.group(1)

                        required_subjects = []
                        for c_idx, subj_name in subject_cols.items():
                            level = None
                            if c_idx < len(row) and row[c_idx]:
                                level_raw = str(row[c_idx]).replace('\n', ' ').strip()
                                level = extract_level(level_raw)

                            # if level is actually another subject name or blank, maybe the real level is on the next line
                            if (not level or len(level) > 10) and r_idx + 1 < len(table) and table[r_idx + 1][0] is None:
                                next_row = table[r_idx + 1]
                                if c_idx < len(next_row) and next_row[c_idx]:
                                    next_level_raw = str(next_row[c_idx]).replace('\n', ' ').strip()
                                    next_level = extract_level(next_level_raw)
                                    if next_level:
                                        # If the current level is a subject string (like in Vet Nursing),
                                        # we append it to the subject name
                                        if level and len(level) > 10:
                                            subj_name = level
                                        level = next_level

                            if level and len(level) < 30:
                                if " or " in level.lower() or " / " in level.lower():
                                    alt_parts = re.split(r'\s+or\s+|\s+/\s+', level, flags=re.IGNORECASE)
                                    for part in alt_parts:
                                        m_subj_lvl = re.match(r'([A-Za-z\s]+)\s+(\d+)', part.strip())
                                        if m_subj_lvl:
                                            required_subjects.append({
                                                "subject": m_subj_lvl.group(1).strip(),
                                                "level": m_subj_lvl.group(2).strip()
                                            })
                                        else:
                                            subjs = re.split(r'\s+or\s+|\s+/\s+', clean_subject_name(subj_name), flags=re.IGNORECASE)
                                            for s in subjs:
                                                s_clean = s.strip()
                                                if s_clean:
                                                    required_subjects.append({
                                                        "subject": s_clean,
                                                        "level": part.strip()
                                                    })
                                else:
                                    subjs = re.split(r'\s+or\s+|\s+/\s+', clean_subject_name(subj_name), flags=re.IGNORECASE)
                                    for s in subjs:
                                        s_clean = s.strip()
                                        if s_clean:
                                            required_subjects.append({
                                                "subject": s_clean,
                                                "level": level
                                            })

                        if aps and course_name and aps.isdigit():
                            faculty_data[current_faculty].append({
                                "course_name": course_name,
                                "duration": duration,
                                "aps": aps,
                                "required_subjects": required_subjects
                            })

    return {k: v for k, v in faculty_data.items() if len(v) > 0}

if __name__ == '__main__':
    data = process_pdf('up.pdf')
    with open('up.json', 'w') as f:
        json.dump(data, f, indent=4)
