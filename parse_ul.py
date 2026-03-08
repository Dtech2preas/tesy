import pdfplumber
import re
import json

def reverse_text_in_header(text):
    if not text: return ""

    if 'hsilgnE' in text: return 'English'
    if 'scitamehtaM' in text or 'shtaM' in text or 'Math' in text: return 'Mathematics'
    if 'lacisyhP' in text or 'secneicSlacisyhP' in text or 'ecneicSlacisyhP' in text: return 'Physical Sciences'
    if 'ecneicSefiL' in text or 'secneicSefiL' in text: return 'Life Sciences'
    if 'SPA' in text: return 'APS'
    if 'noitatneirOefiL' in text: return 'Life Orientation'
    if 'lanoitiddA' in text:
        if '1' in text: return 'Additional Subject 1'
        if '2' in text: return 'Additional Subject 2'
        return 'Additional Subjects'
    if 'ydutSfosraeY' in text: return 'Duration'

    if 'egaugnaL' in text or 'nevihsT' in text or 'agnostiX' in text or 'idepeS' in text: return 'Language'
    if 'yhpargoeG' in text: return 'Geography'
    if 'larutlucirgA' in text: return 'Agricultural Subject'
    if 'ycaretiL' in text or 'Literacy' in text: return 'Mathematics Literacy'
    if 'stcejbuS' in text or 'stcejbus' in text: return 'Additional Subjects'
    if 'yhP efiL' in text or 'ecneicSlacis' in text: return 'Physical Sciences'
    if 'scimonocE' in text: return 'Economics'
    if 'gnitnuoccA' in text: return 'Accounting and Business Studies'

    clean_text = text.replace('\n', ' ').strip()
    if len(clean_text) > 3 and 'hsilgnE' not in clean_text:
        reversed_text = clean_text[::-1]
        if any(w in reversed_text for w in ['Mathematics', 'Science', 'English', 'Language', 'Subject', 'Economics']):
            return reversed_text
    return clean_text

def extract_level_percentage(val):
    if not val: return None, None
    val = val.strip().replace('\n', ' ')

    level_match = re.search(r'^(\d)', val)
    level = level_match.group(1) if level_match else None

    perc_match = re.search(r'\(([\d\-\.]+)\%?\)', val)
    percentage = None
    if perc_match:
        percentage = perc_match.group(1).replace(' ', '')
        if not percentage.endswith('%'): percentage = percentage + '%'
    if not percentage and '%' in val:
         alt_match = re.search(r'(\d+-\d+%|\d+%)', val)
         if alt_match: percentage = alt_match.group(1).replace(' ', '')
         else:
             alt_match2 = re.search(r'(\d+-\s?\d+%?)', val)
             if alt_match2:
                 percentage = alt_match2.group(1).replace(' ', '')
                 if not percentage.endswith('%'): percentage += '%'

    # Fix for weird extract '9%'
    if percentage == '9%':
        if '50-5' in val: percentage = '50-59%'

    if percentage == '6069%':
        percentage = '60-69%'

    return level, percentage

def process_pdf(pdf_path):
    faculties_data = {}
    current_faculty = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if table[0] and table[0][0] and "Faculty of" in table[0][0]:
                    current_faculty = table[0][0].strip()
                    if current_faculty not in faculties_data: faculties_data[current_faculty] = []
                elif current_faculty is None:
                    for row in table:
                        if row and row[0] and "Faculty of" in row[0]:
                            current_faculty = row[0].strip()
                            if current_faculty not in faculties_data: faculties_data[current_faculty] = []
                            break
                if not current_faculty: continue

                header_row, subject_start_col, aps_col, duration_col = None, -1, -1, -1

                for row_idx, row in enumerate(table):
                    if not any(row): continue

                    squashed_header = False
                    if row[1] and 'Required Subjects' in row[1] and 'SPA' in row[1]:
                        header_row = ['', '', 'Duration', 'English', 'Mathematics', 'Economics', 'Additional Subjects', 'APS', '']
                        squashed_header = True

                    is_header = squashed_header or any('SPA' in (c or '').replace('\n', '') or 'hsilgnE' in (c or '').replace('\n', '') for c in row)

                    if is_header:
                        if not squashed_header:
                            header_row = [reverse_text_in_header(c) if c else "" for c in row]

                        for i, h in enumerate(header_row):
                            if h in ['English', 'Mathematics', 'Life Orientation', 'Language']:
                                if subject_start_col == -1: subject_start_col = i
                            if h == 'Duration': duration_col = i
                            if h == 'APS': aps_col = i
                        if subject_start_col == -1: subject_start_col = 3

                        i = row_idx + 1
                        while i < len(table):
                            course_name = None
                            for cell in table[i]:
                                if cell and any(k in cell for k in ['Bachelor', 'BSc', 'BA ', 'BEd', 'BCom', 'LLB', 'BDev', 'BAdmin', 'BOptom', 'BNur', 'BPha', 'Dip', 'MBChB', 'BAcc']):
                                    course_name = " ".join([c.strip() for c in table[i] if c and isinstance(c, str)])
                                    course_name = re.sub(r'\s+', ' ', course_name)
                                    match = re.search(r'([A-Za-z\s\(\)\-\&\,]+)', course_name)
                                    if match: course_name = match.group(1).strip()
                                    break

                            if course_name:
                                # Course name specific cleanups (from reverse text fragmentation)
                                course_name = re.sub(r'^(YCN|AM|OC|DNA|SC|IMON|TN|E\s|MEGAN)\s?', '', course_name).strip()
                                course_name = re.sub(r'^(ENIC|IDEM)\s?', '', course_name).strip()
                                course_name = re.sub(r'^(SECNEICSERACHTLAEH|SECNEICSEFIL\&RALUCELOM|RETUPMOCDNALACITAMEHTAM SECNEICS|W\s|A\s|L\s)\s?', '', course_name).strip()
                                course_name = re.sub(r'^NOITACUDE\s?', '', course_name).strip()

                                req_row = table[i+1] if i+1 < len(table) else None

                                if req_row:
                                    duration, aps, required_subjects = None, None, []

                                    # Fix BCom Management shifted column issues
                                    if ("Commerce" in course_name or "Administration" in course_name or "Development" in course_name) and "Management" in current_faculty:
                                        dur_col_real = 2 if len(req_row) > 2 and re.match(r'^\d$', str(req_row[2]).strip()) else 1
                                        if len(req_row) > dur_col_real:
                                            duration = str(req_row[dur_col_real]).strip()
                                        if len(req_row) > dur_col_real + 1 and req_row[dur_col_real+1]:
                                            lvl, perc = extract_level_percentage(req_row[dur_col_real+1])
                                            if lvl or perc:
                                                o = {"subject": "English"}
                                                if lvl: o["level"] = lvl
                                                if perc: o["percentage"] = perc
                                                required_subjects.append(o)
                                        if len(req_row) > dur_col_real + 2 and req_row[dur_col_real+2]:
                                            lvl, perc = extract_level_percentage(req_row[dur_col_real+2])
                                            if lvl or perc:
                                                o = {"subject": "Mathematics"}
                                                if lvl: o["level"] = lvl
                                                if perc: o["percentage"] = perc
                                                required_subjects.append(o)
                                        # Just search backwards for APS
                                        for c in reversed(req_row):
                                            if c and re.match(r'^\d{2}$', str(c).strip()):
                                                aps = str(c).strip()
                                                break

                                    else:
                                        for idx, cell in enumerate(req_row):
                                            if cell and ('Optometrist' in cell or 'Medical Scientist' in cell or 'Plant B r e e d e rs' in cell or 'P l a n t' in cell or 'APS total' in cell and 'BAcc' in course_name):

                                                levels = re.findall(r'^(\d(?: \d)+)', cell.strip())
                                                if not levels:
                                                    levels = re.findall(r'(\d \d \d \d \d)', cell)
                                                    if not levels:
                                                        levels = re.findall(r'(\d \d \d \d)', cell)
                                                if not levels and 'BAcc' in course_name:
                                                    levels = re.findall(r'(\d \d \d)', cell)

                                                percentages = re.findall(r'(\(\d{2}- ?\d{2}\%?\))', cell.replace(' ', ''))

                                                apss = re.search(r'\n(\d{2})\n', cell)
                                                if not apss: apss = re.search(r'(\d{2})\n', cell)
                                                if not apss: apss = re.search(r'to 24', cell)
                                                if not apss and 'BAcc' in course_name: apss = re.search(r'Tax 30\n', cell)

                                                if apss:
                                                    aps = apss.group(1) if 'to 24' not in apss.group(0) and 'Tax 30' not in apss.group(0) else ("24" if 'to 24' in apss.group(0) else "30")

                                                if levels:
                                                    lvl_list = levels[0].split(' ')
                                                    for k, lvl in enumerate(lvl_list):
                                                        subj_idx = subject_start_col + k
                                                        if subj_idx < len(header_row):
                                                            subj_name = header_row[subj_idx]
                                                            if aps_col != -1 and subj_idx == aps_col: continue
                                                            if not subj_name or len(subj_name) < 3: continue

                                                            perc = percentages[k].strip('()') if k < len(percentages) else None
                                                            if perc and '-' in perc and not perc.endswith('%'): perc += '%'

                                                            subj_obj = {"subject": subj_name, "level": lvl}
                                                            if perc: subj_obj["percentage"] = perc
                                                            required_subjects.append(subj_obj)
                                                break

                                        if not required_subjects:
                                            if duration_col == -1: duration_col = subject_start_col - 1
                                            if 0 <= duration_col < len(req_row) and req_row[duration_col]:
                                                 m = re.search(r'^(\d)', req_row[duration_col].strip())
                                                 if m: duration = m.group(1)

                                            if aps_col == -1: aps_col = len(header_row) - 1
                                            if 0 <= aps_col < len(req_row) and req_row[aps_col]:
                                                 m = re.search(r'(\d{2})', req_row[aps_col])
                                                 if m: aps = m.group(1)

                                            if subject_start_col != -1:
                                                for col_idx in range(subject_start_col, len(header_row)):
                                                    if col_idx == aps_col: continue
                                                    subj_name = header_row[col_idx]
                                                    if not subj_name or len(subj_name) < 3 or 'School' in subj_name or 'Career' in subj_name: continue

                                                    if col_idx < len(req_row) and req_row[col_idx]:
                                                        level, percentage = extract_level_percentage(req_row[col_idx])
                                                        subj_obj = {"subject": subj_name}
                                                        if level: subj_obj["level"] = level
                                                        if percentage: subj_obj["percentage"] = percentage
                                                        if level or percentage or "Additional" in subj_name:
                                                            required_subjects.append(subj_obj)

                                    if 'Optometry' in course_name and not duration: duration = "4"
                                    if 'Medical Scie' in course_name and not duration: duration = "3"
                                    if 'Plant Prod' in course_name and not duration: duration = "4"
                                    if 'BAcc' in course_name and not duration: duration = "3"

                                    faculties_data[current_faculty].append({
                                        "course_name": course_name.strip(),
                                        "duration": duration,
                                        "aps": aps,
                                        "required_subjects": required_subjects
                                    })
                                i += 1
                            i += 1
                        break

    with open('ul.json', 'w') as f: json.dump(faculties_data, f, indent=4)

if __name__ == "__main__": process_pdf("ul.pdf")
