import pdfplumber
import re
import json

def parse_subjects(subject_text):
    if not subject_text: return []
    lines = subject_text.split('\n')
    subjects = []

    for line in lines:
        line = line.strip()
        if not line: continue

        # Remove trailing " or"
        if line.lower().endswith(' or'):
            line = line[:-3].strip()

        if line.startswith("Preference will be given") or line.startswith("FOR APPLICANTS") or line.startswith("A Senior Certificate") or line.startswith("Applicants are also required") or line.startswith("Proof of employment") or line.startswith("CERTIFICATE OBTAINED"):
            continue

        m1 = re.match(r'Level\s+(\d+)\s+for\s+(.*)', line, re.IGNORECASE)
        if m1:
            level = m1.group(1).strip()
            subj_group = m1.group(2).strip()
            subjs = re.split(r'\s+or\s+|\s+and/or\s+', subj_group)
            for s in subjs:
                s = s.strip()
                if s: subjects.append({"subject": s, "level": level})
            continue

        m2 = re.search(r'^(.*?)\s+(\d)$', line)
        if m2:
            subj_group = m2.group(1).strip()
            level = m2.group(2).strip()
            subjs = re.split(r'\s+or\s+|\s+and/or\s+', subj_group)
            for s in subjs:
                s = s.strip()
                if s: subjects.append({"subject": s, "level": level})
            continue

        m3 = re.search(r'^(\d)\s+for\s+(.*)$', line, re.IGNORECASE)
        if m3:
            level = m3.group(1).strip()
            subj_group = m3.group(2).strip()
            subjs = re.split(r'\s+or\s+|\s+and/or\s+', subj_group)
            for s in subjs:
                s = s.strip()
                if s: subjects.append({"subject": s, "level": level})
            continue

        if len(line) > 2:
            subjs = re.split(r'\s+or\s+|\s+and/or\s+', line)
            for s in subjs:
                s = s.strip()
                if s: subjects.append({"subject": s, "level": "Unspecified"})

    return subjects

def get_faculty_name(text):
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if "YTLUCAF" in line:
            parts = []
            for j in range(i, -1, -1):
                if 'www.tut.ac.za' in lines[j] or '© Tshwane' in lines[j] or 'supmaC' in lines[j]:
                    break
                val = lines[j].strip()
                if val == '|':
                    break
                if not val:
                    continue
                parts.append(val[::-1])
            return " ".join(parts).replace("  ", " ").strip()
    return "Unknown Faculty"

def extract_tut_data(pdf_path, output_json):
    courses_by_faculty = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page_num in range(3, len(pdf.pages)):
            page = pdf.pages[page_num]
            text = page.extract_text()
            if not text: continue

            faculty_name = get_faculty_name(text)

            tables = page.extract_tables()
            if not tables: continue

            if faculty_name not in courses_by_faculty:
                courses_by_faculty[faculty_name] = []

            last_course_ref = None
            for table in tables:
                for row_idx, row in enumerate(table):
                    cleaned_row = [cell if cell is not None else "" for cell in row]
                    if len(cleaned_row) < 6: continue

                    # Try to find the course name
                    course_name = ""
                    course_idx = -1
                    for i in range(2):
                        if cleaned_row[i].strip() and cleaned_row[i].strip() not in ["PROGRAMME", "TEACHING COURSES", "ADMISSION REQUIREMENTS"]:
                            course_name = cleaned_row[i].replace('\n', ' ').strip()
                            course_idx = i
                            break

                    # If we don't have a course name, it might be a continuation of the previous row (like another APS for another subject)
                    if not course_name:
                        # Check if it has an APS score or something and append to the last course
                        if last_course_ref:
                            aps_val = ""
                            # Scan from the right side of cleaned_row for the APS string
                            for j in range(len(cleaned_row)-1, -1, -1):
                                val = cleaned_row[j].replace('\n', ' ').strip()
                                if val.isdigit() or '(' in val:
                                    aps_val = val
                                    break
                            if aps_val and aps_val not in last_course_ref['aps']:
                                last_course_ref['aps'] += " / " + aps_val
                        continue

                    duration = ""
                    duration_idx = -1
                    # Search from course_idx+1 onwards for a single digit representing duration
                    for k in range(course_idx+1, min(course_idx+5, len(cleaned_row))):
                        if cleaned_row[k].strip().isdigit() and len(cleaned_row[k].strip()) == 1:
                            duration = cleaned_row[k].strip()
                            duration_idx = k
                            break

                    if duration_idx == -1:
                        continue

                    subject_idx = duration_idx + 2
                    aps_idx = duration_idx + 3

                    subject_text = cleaned_row[subject_idx] if subject_idx < len(cleaned_row) else ""
                    aps_text = cleaned_row[aps_idx].replace('\n', ' ').strip() if aps_idx < len(cleaned_row) else ""

                    subjects = parse_subjects(subject_text)

                    course_data = {
                        "course_name": course_name,
                        "duration": duration,
                        "aps": aps_text,
                        "required_subjects": subjects
                    }
                    courses_by_faculty[faculty_name].append(course_data)
                    last_course_ref = course_data

    with open(output_json, 'w') as f:
        json.dump(courses_by_faculty, f, indent=4)

if __name__ == "__main__":
    extract_tut_data("tut.pdf", "tut.json")
    print("Done")
