import requests
from bs4 import BeautifulSoup
import json
import re

url = "https://universityqualifications.co.za/universities/university-of-johannesburg/programmes"

def get_level(text):
    match = re.search(r'(\d)\s*\((\d+)%\+\)', text)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r'(\d+)\s*%', text)
    if match:
        return "", match.group(1)
    match = re.search(r'(?:level|code)\s*(\d)', text, re.I)
    if match:
        return match.group(1), ""

    # Check for just single digit levels
    match = re.search(r'\s*(\d)\s*', text)
    if match:
        return match.group(1), ""
    return "", ""

def parse_subjects(text):
    # Standardize commas, semicolons, and ORs
    required_subjects = []

    # Split text intelligently
    parts = re.split(r'[,;]|(?<=\)) OR |(?<=\+) OR ', text)

    for part in parts:
        if "APS" in part and "with Mathematics" not in part: continue
        if "Qualification Code" in part: continue
        part = part.strip()
        if not part: continue

        # English: 5 (60%+)
        if ":" in part:
            sub_parts = part.split(':')
            subject = sub_parts[0].strip()
            if "APS" in subject: continue
            if "Qualification Code" in subject: continue
            if "not accepted" in part.lower() or "not applicable" in part.lower(): continue

            lvl, pct = get_level(sub_parts[1])
            if lvl or pct:
                req = {"subject": subject}
                if lvl: req["level"] = lvl
                if pct: req["percentage"] = pct
                required_subjects.append(req)

        # Mathematics / Technical Mathematics 5 (60%+)
        else:
            if "APS" in part: continue
            if "Qualification Code" in part: continue
            if "not accepted" in part.lower() or "not applicable" in part.lower(): continue
            match = re.search(r'([A-Za-z\s/]+)\s+(\d)\s*\((\d+)%\+\)', part)
            if match:
                subj = match.group(1).strip()
                # Split alternative inline subjects
                subjs = subj.split('/')
                if len(subjs) > 1:
                    group = []
                    for s in subjs:
                        group.append({"subject": f"OR {s.strip()}", "level": match.group(2), "percentage": match.group(3)})
                    if group:
                        group[0]["subject"] = group[0]["subject"].replace("OR ", "").strip()
                        required_subjects.extend(group)
                else:
                    required_subjects.append({"subject": subj, "level": match.group(2), "percentage": match.group(3)})
            else:
                 # English 5 (60%+)
                 match2 = re.search(r'([A-Za-z\s]+)\s+(\d)\s*\((\d+)%\+\)', part)
                 if match2:
                     if "APS" not in match2.group(1) and "Qualification Code" not in match2.group(1):
                         required_subjects.append({"subject": match2.group(1).strip(), "level": match2.group(2), "percentage": match2.group(3)})

    return required_subjects

def scrape():
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    programs_by_faculty = {}

    for article in soup.find_all('article', class_='card'):
        faculty_badge = article.find('span', string=lambda text: text and text.strip() in [
            'College of Business and Economics',
            'Engineering and the Built Environment',
            'Art, Design and Architecture',
            'Education',
            'Health Sciences',
            'Humanities',
            'Law'
        ])
        faculty = faculty_badge.text.strip() if faculty_badge else ""
        if not faculty:
             badges = article.find_all('span', class_='badge')
             for b in badges:
                  if 'bg-soft-primary' in b.get('class', []):
                       faculty = b.text.strip()

        if not faculty:
            faculty = "Unknown Faculty"

        course_name_el = article.find('h3')
        course_name = course_name_el.text.strip() if course_name_el else "Unknown Course"

        badges = article.find_all('span', class_='badge')
        duration = ""
        aps = ""
        for badge in badges:
            text = badge.text.strip()
            if 'years' in text or 'year' in text:
                match = re.search(r'(\d+)', text)
                if match: duration = match.group(1)
            if 'APS:' in text:
                aps_match = re.search(r'APS:\s*(\d+)', text)
                if aps_match:
                    aps = aps_match.group(1)

        key_reqs = ""
        add_reqs = ""

        for p_title in article.find_all('p', class_='text-uppercase'):
            title_text = p_title.text.strip().lower()

            if 'key requirements' in title_text:
                req_p = p_title.find_next_sibling('p')
                if req_p:
                    key_reqs = req_p.text.strip()
                else:
                    details = p_title.find_next_sibling('details')
                    if details:
                        req_p = details.find('p')
                        if req_p: key_reqs = req_p.text.strip()

            elif 'additional requirements' in title_text:
                req_p = p_title.find_next_sibling('p')
                if req_p:
                    add_reqs = req_p.text.strip()
                else:
                    details = p_title.find_next_sibling('details')
                    if details:
                        req_p = details.find('p')
                        if req_p: add_reqs = req_p.text.strip()

        raw_requirements = f"{key_reqs} {add_reqs}".strip()

        required_subjects = []
        non_academic_requirements = []

        non_academic_keywords = [
            "interview", "portfolio", "audition", "medical examination",
            "selection process", "questionnaire", "fitness assessment",
            "phobias evaluation", "letter of recommendation", "assignment",
            "visit the on campus", "police clearance", "registration requirements",
            "required documentation", "work experience", "practical assessments",
            "committee", "upgraded their matric results", "specific mathematical literacy subject requirement",
            "duration usually"
        ]

        sentences = re.split(r'[.!?]', raw_requirements)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence: continue

            is_non_academic = any(keyword.lower() in sentence.lower() for keyword in non_academic_keywords)
            if is_non_academic:
                non_academic_requirements.append(sentence)
            else:
                # Add parsed subjects
                parsed = parse_subjects(sentence)
                required_subjects.extend(parsed)


        course_obj = {
            "course_name": course_name,
            "course_code": "",
            "duration": duration,
            "aps": aps,
            "required_subjects": required_subjects,
            "nonAcademicRequirements": non_academic_requirements,
            "rawRequirements": raw_requirements
        }

        if faculty not in programs_by_faculty:
            programs_by_faculty[faculty] = []
        programs_by_faculty[faculty].append(course_obj)

    with open('universities/uj/data.json', 'w') as f:
        json.dump(programs_by_faculty, f, indent=4)

if __name__ == "__main__":
    scrape()
