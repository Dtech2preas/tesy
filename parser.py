import pdfplumber
import json
import re

def clean_value(val):
    if not val:
        return ""
    return str(val).replace("\n", " ").strip()

def parse_wits_pdf(pdf_path):
    wits_data = {}

    with pdfplumber.open(pdf_path) as pdf:

        for i in range(7, 13):
            page = pdf.pages[i]
            text = page.extract_text()
            if not text: continue

            # Find faculty name
            faculty_name = ""
            lines = text.split("\n")
            for line in lines[:5]:
                if "FACULTY" in line.upper():
                    faculty_name = line.strip()
                    break

            if not faculty_name:
                continue

            if faculty_name not in wits_data:
                wits_data[faculty_name] = []

            tables = page.extract_tables()
            if not tables:
                continue

            for table_idx, table in enumerate(tables):
                if len(table) < 2:
                    continue

                header = [clean_value(h) for h in table[0]]

                # Health sciences has weird structure where table 1 is valid
                if 'Programme' not in header:
                    if len(table) > 1 and 'Programme' in [clean_value(h) for h in table[1]]:
                        header = [clean_value(h) for h in table[1]]
                        table = table[1:]
                    else:
                        continue # Not a valid table

                print(f"Parsing {faculty_name} Table {table_idx} with header {header}")

                # To handle wrapped course names, we need to look ahead
                skip_rows = 0
                for row_idx, row in enumerate(table[1:]):
                    if skip_rows > 0:
                        skip_rows -= 1
                        continue

                    if not row or not row[0]: continue

                    course_name = clean_value(row[0]).replace("\u2022", "").strip()

                    # Fix merged columns in the same row
                    if len(row) > 1 and row[1] and "Duration" not in clean_value(row[1]) and not clean_value(row[1]).isdigit():
                        course_name += " " + clean_value(row[1]).replace("\u2022", "").strip()

                    # Check next row to see if it's a continuation of the course name
                    # (continuation rows typically have empty columns for duration, APS, and subjects)
                    next_row_idx = row_idx + 1
                    while next_row_idx < len(table[1:]):
                        next_row = table[1:][next_row_idx]
                        if next_row and next_row[0]:
                            # If duration/aps are empty, it might be a continuation
                            has_data = False
                            for col in next_row[1:]:
                                if clean_value(col):
                                    has_data = True
                                    break

                            # Exception for Health Sciences where col 1 might be duration and it could be empty
                            if not has_data or (len(next_row) > 2 and not clean_value(next_row[1]) and not clean_value(next_row[2])):
                                # Some rows might just be blank subjects, but for Health Sciences, continuation name is common
                                # Let's only merge if it's explicitly short and looks like a continuation
                                continuation_text = clean_value(next_row[0]).replace("\u2022", "").strip()
                                if continuation_text and not continuation_text.isdigit() and len(continuation_text) < 30:
                                    course_name += " " + continuation_text
                                    skip_rows += 1
                                    next_row_idx += 1
                                    continue
                        break


                    duration = ""
                    aps = ""
                    start_subj_col = 4

                    if "HEALTH SCIENCES" in faculty_name.upper():
                        if len(row) > 1: duration = clean_value(row[1])
                        # Health Sciences generally has Selection/NBT rather than explicit APS
                        aps = ""
                        start_subj_col = 4
                    else:
                        if len(row) > 2: duration = clean_value(row[2])
                        if len(row) > 3: aps = clean_value(row[3])
                        start_subj_col = 4

                    aps = re.sub(r'[^0-9]', '', aps)

                    # Ensure numeric duration
                    duration = re.sub(r'[^0-9]', '', duration)

                    if not duration and not aps and not "HEALTH SCIENCES" in faculty_name.upper():
                        continue

                    required_subjects = []

                    for col_idx in range(start_subj_col, len(row)):
                        if col_idx >= len(header): break

                        subject_val = clean_value(row[col_idx])
                        if not subject_val or len(subject_val) > 20:
                            continue

                        level_raw = re.sub(r'[^0-9%]', ' ', subject_val).strip()
                        level = ' '.join(level_raw.split())
                        if level:
                            subj_name = clean_value(header[col_idx]).replace("\n", " ")
                            if not subj_name:
                                if "Life Sciences and/or" in text and col_idx == 9:
                                    subj_name = "Life Sciences and/or Physical Sciences"

                            if "First Additional Language" in subj_name:
                                required_subjects.append({
                                    "subject": "English Home Language",
                                    "level": level
                                })
                                required_subjects.append({
                                    "subject": "English First Additional Language",
                                    "level": level
                                })
                            elif "and/or" in subj_name:
                                parts = subj_name.split("and/or")
                                for part in parts:
                                    required_subjects.append({
                                        "subject": part.strip(),
                                        "level": level
                                    })
                            else:
                                required_subjects.append({
                                    "subject": subj_name,
                                    "level": level
                                })

                    course_name = course_name.strip()
                    # Remove any random spaces added by the clean process
                    course_name = ' '.join(course_name.split())

                    if course_name and (duration or aps or required_subjects):
                        wits_data[faculty_name].append({
                            "course_name": course_name,
                            "course_code": "",  # The PDF prospectus does not provide explicit course codes
                            "duration": duration,
                            "aps": aps,
                            "required_subjects": required_subjects
                        })

    with open("wits.json", "w") as f:
        json.dump(wits_data, f, indent=4)

parse_wits_pdf("Wits SLO Grade 12_100125.pdf")
