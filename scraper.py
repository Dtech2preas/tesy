import requests
from bs4 import BeautifulSoup
import json
import re
import argparse

def split_subjects(subject_string, level, percentage):
    """Splits subjects by OR, AND/OR, and returns a list of requirement dicts."""
    # Normalize separators
    text = subject_string.replace(" AND/OR ", " OR ")

    # We shouldn't split 'English Home Language or First Additional Language'
    # because that broke the frontend's understanding of that specific subject combo
    # let's only split if explicitly asked, but given the user feedback,
    # they want the original string back exactly as it was.
    pass


def clean_subject(sub):
    sub = re.sub(r'\s+at$', '', sub).strip()
    sub = re.sub(r'^and\s+', '', sub).strip()
    sub = re.sub(r'^at$', '', sub).strip()
    return sub

def extract_subjects_uct(text):
    reqs = []

    for sm in re.finditer(r'>=\s*(\d+)%\s*for\s*([A-Za-z\s]+)(?:,|and|\.)', text, re.IGNORECASE):
        sub = clean_subject(sm.group(2))
        if sub and "score" not in sub.lower() and "portfolio" not in sub.lower() and "fps" not in sub.lower() and "wps" not in sub.lower() and sub.lower() not in ['and', 'or', 'average of', 'average']:
            reqs.append({"subject": sub, "level": "", "percentage": sm.group(1).strip()})

    for sm in re.finditer(r'([A-Za-z\s]+(?:\s+(?:and|or)\s+[A-Za-z\s]+)?)\s*at\s*(\d+)%', text, re.IGNORECASE):
        subs_raw = sm.group(1).strip()
        pct = sm.group(2).strip()
        for sub in re.split(r'\s+(?:and|or)\s+', subs_raw, flags=re.IGNORECASE):
            sub = clean_subject(sub)
            if sub.lower().startswith('or '): sub = sub[3:].strip()
            if sub and "score" not in sub.lower() and "portfolio" not in sub.lower() and "fps" not in sub.lower() and "wps" not in sub.lower() and sub.lower() not in ['and', 'or', 'average of', 'average']:
                if sub.startswith("English (Home"): sub = "English"
                reqs.append({"subject": sub, "level": "", "percentage": pct})

    for sm in re.finditer(r'([A-Za-z\s]+)\s+(\d+)%', text):
        sub = clean_subject(sm.group(1))
        if sub.lower().startswith('or '): sub = sub[3:].strip()
        if sub and "score" not in sub.lower() and "portfolio" not in sub.lower() and "fps" not in sub.lower() and "wps" not in sub.lower() and "mathematics at" not in sub.lower() and sub.lower() not in ['and', 'or', 'average of', 'average']:
            reqs.append({"subject": sub, "level": "", "percentage": sm.group(2).strip()})

    for sm in re.finditer(r'([A-Za-z\s]+)\s+(\d+)%\+', text):
        sub = clean_subject(sm.group(1))
        if sub.lower().startswith('or '): sub = sub[3:].strip()
        if sub and "score" not in sub.lower() and "portfolio" not in sub.lower() and "fps" not in sub.lower() and "wps" not in sub.lower() and sub.lower() not in ['and', 'or', 'average of', 'average']:
            reqs.append({"subject": sub, "level": "", "percentage": sm.group(2).strip()})

    unique_reqs = []
    seen = set()
    for r in reqs:
        # Ignore obvious garbage subjects
        if r['subject'] not in seen and r['subject'] and len(r['subject']) < 40 and r['subject'].lower() not in ['and', 'or', 'average of', 'average']:
            seen.add(r['subject'])
            unique_reqs.append(r)
    return unique_reqs

def parse_uct_course(card):
    faculty_badge = card.find('span', class_=re.compile("bg-soft-primary"))
    title_tag = card.find(lambda tag: tag.name in ['h3', 'h4', 'h5'])

    if not faculty_badge or not title_tag:
        return None, None

    faculty_name = faculty_badge.get_text(strip=True).split(" - ")[0].upper().strip().replace(" AND ", " & ")
    course_name = title_tag.get_text(strip=True)

    badges = card.find_all('span', class_=re.compile("rounded-pill"))
    duration = ""
    aps = ""
    for badge in badges:
        text = badge.get_text(strip=True)
        if "years" in text.lower() or "year" in text.lower():
            m = re.search(r'\d+', text)
            if m: duration = m.group()
        if "APS" in text:
            p = text.split(":")
            if len(p) > 1: aps = p[1].strip()

    req_header = card.find(lambda tag: tag.name == 'p' and "Key Requirements" in tag.get_text())
    req_text = ""
    if req_header:
        for sibling in req_header.find_next_siblings():
            if sibling.name == 'p' and "Show full requirements" in sibling.get_text(): continue
            if sibling.name == 'p' and "Additional Requirements" in sibling.get_text(): break
            req_text += sibling.get_text(strip=True) + " "

    req_text = req_text.replace("Show full requirements", "").strip()

    bands = {}
    normalized_text = re.sub(r'\(Band ([A-C])\)', r'Band \1', req_text, flags=re.IGNORECASE)
    band_splits = re.split(r'(Band [A-C])', normalized_text, flags=re.IGNORECASE)

    global_text = band_splits[0]
    global_subjects = extract_subjects_uct(global_text)

    if len(band_splits) > 1:
        for i in range(1, len(band_splits), 2):
            band_name = band_splits[i].strip().upper()
            band_text = band_splits[i+1]

            fps_match = re.search(r'(\d+)\s*FPS', band_text, re.IGNORECASE)
            wps_match = re.search(r'(\d+)\s*WPS', band_text, re.IGNORECASE)
            score = fps_match.group(1) if fps_match else (wps_match.group(1) if wps_match else "")
            score_type = "FPS" if fps_match else ("WPS" if wps_match else "")

            band_subjects = extract_subjects_uct(band_text)

            merged = list(global_subjects)
            seen_subs = {s['subject'] for s in global_subjects}
            for bs in band_subjects:
                if bs['subject'] not in seen_subs:
                    merged.append(bs)
                    seen_subs.add(bs['subject'])

            bands[band_name] = {
                "score_type": score_type,
                "score": score,
                "required_subjects": merged,
                "raw_text": (band_name + band_text).strip()
            }
    else:
        fps_match = re.search(r'(\d+)\s*FPS', normalized_text, re.IGNORECASE)
        wps_match = re.search(r'(\d+)\s*WPS', normalized_text, re.IGNORECASE)
        score = fps_match.group(1) if fps_match else (wps_match.group(1) if wps_match else "")
        score_type = "FPS" if fps_match else ("WPS" if wps_match else "")

        bands["DEFAULT"] = {
            "score_type": score_type,
            "score": score,
            "required_subjects": global_subjects,
            "raw_text": normalized_text
        }

    bands_list = []
    for k, v in bands.items():
        bands_list.append({
            "band_name": k,
            **v
        })

    course_data = {
        "course_name": course_name,
        "course_code": "",
        "duration": duration,
        "aps": aps,
        "bands": bands_list,
        "req_text": req_text,
        "required_subjects": bands_list[0]["required_subjects"] if bands_list else []
    }

    if bands_list:
        course_data["fps"] = bands_list[0]["score"] if bands_list[0]["score_type"] == "FPS" else ""
        course_data["wps"] = bands_list[0]["score"] if bands_list[0]["score_type"] == "WPS" else ""

    return faculty_name, course_data

def scrape_university(url, output_file):
    print(f"Scraping data from: {url}")
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})

    if response.status_code != 200:
        print(f"Failed to fetch page. Status code: {response.status_code}")
        return

    soup = BeautifulSoup(response.content, 'html.parser')

    faculties = {}

    # Find all cards containing program data
    cards = soup.find_all('div', class_="card-body")


    if "cape-town" in url or "uct" in url:
        for card in cards:
            fname, cdata = parse_uct_course(card)
            if fname and cdata:
                if fname not in faculties: faculties[fname] = []
                faculties[fname].append(cdata)

        with open(output_file, 'w') as f:
            json.dump(faculties, f, indent=4)
        print(f"Successfully scraped {sum(len(courses) for courses in faculties.values())} courses across {len(faculties)} faculties.")
        print(f"Data saved to {output_file}")
        return

    for card in cards:
        # Extract Faculty
        faculty_badge = card.find('span', class_=re.compile("bg-soft-primary"))
        title_tag = card.find(lambda tag: tag.name in ['h3', 'h4', 'h5'])

        if not title_tag:
            continue

        faculty_text = faculty_badge.get_text(strip=True) if faculty_badge else ""
        if not faculty_text:
            continue # Skip header/summary cards

        faculty_name = faculty_text.split(" - ")[0].upper().strip()
        faculty_name = faculty_name.replace(" AND ", " & ")

        # Extract Course Name
        course_name = title_tag.get_text(strip=True)

        # Extract Duration and APS
        badges = card.find_all('span', class_=re.compile("rounded-pill"))
        duration = ""
        aps = ""

        for badge in badges:
            text = badge.get_text(strip=True)
            if "years" in text.lower():
                duration_match = re.search(r'\d+', text)
                if duration_match:
                    duration = duration_match.group()
            if "APS" in text:
                aps_parts = text.split(":")
                if len(aps_parts) > 1:
                    aps = aps_parts[1].strip()

        # Extract Key Requirements
        requirements = []
        req_header = card.find(lambda tag: tag.name == 'p' and "Key Requirements" in tag.get_text())
        if req_header:
            req_text_tag = req_header.find_next_sibling('p')
            if req_text_tag:
                req_text = req_text_tag.get_text(strip=True)

                # Basic Parsing of subjects: "Subject X(Y%+), Subject Z(Level)"
                # The user noted that splitting "OR" inside subjects like "English Home Language OR First Additional Language"
                # broke the frontend because it created "English Home Language (Level 6) (70)" and "First Additional Language (Level 6) (70)"
                # and the user failed because they didn't have "First Additional Language".

                # Separate out dot delimited sentences since sometimes APS is mentioned in the same line
                sentences = re.split(r'\.\s*', req_text)

                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence: continue

                    # Handle case where "Minimum APS" is listed as a requirement text and skip it to prevent it becoming a subject
                    if "minimum aps" in sentence.lower():
                        continue

                    parts = re.split(r'[,;]\s*|\s+and\s+(?![a-zA-Z]+\s+only)|\s+&\s+', sentence, flags=re.IGNORECASE)
                    for part in parts:
                        part = part.strip()
                        if not part: continue
                        if "nsc-deg" in part.lower() or "nsc deg" in part.lower():
                            part = re.sub(r'NSC-?Deg with ', '', part, flags=re.IGNORECASE)
                            part = part.strip()

                        if "minimum aps" in part.lower():
                            continue

                        # Try splitting by " OR " ONLY for completely separate subjects with their own level (e.g. Maths 4 OR Maths Lit 5)
                        # For things like "English Home Language or First Additional Language: Level 4" we DO NOT split.

                        # Clean trailing colons from subjects if present

                        # Pattern 1: Subject Level(Percentage%+) e.g., Mathematics 5(60%+)
                        # Or Subject Code 4, Subject 6, Subject 5/FAL 6
                        match = re.search(r'(.*?)\s+(?:Code|Level)?\s*(\d+)(?:\s*\(?(\d+)%?\+?\)?|\s*/.*?)?$', part, re.IGNORECASE)
                        if match and "minimum" not in part.lower():
                            subject = match.group(1).strip()
                            if subject.endswith(':'): subject = subject[:-1].strip()
                            level = match.group(2)
                            percentage = match.group(3) if match.group(3) else ""

                            requirements.append({"subject": subject, "level": level, "percentage": percentage})
                        else:
                            # Pattern 2: Subject: Level X or Subject: X
                            match_level = re.search(r'(.*?):\s*(?:Code|Level\s*)?(\d+|null)', part, re.IGNORECASE)
                            if match_level and "minimum" not in part.lower():
                                subject = match_level.group(1).strip()
                                if subject.endswith(':'): subject = subject[:-1].strip()
                                level = match_level.group(3)
                                if level.lower() != 'null':
                                    requirements.append({"subject": subject, "level": level})
                            else:
                                if "minimum of" in part.lower() or part.lower().strip() == "minimum":
                                    continue
                                # Fallback just keep the string
                                requirements.append({"subject": part, "level": ""})

        course_data = {
            "course_name": course_name,
            "course_code": "",
            "duration": duration,
            "aps": aps,
            "required_subjects": requirements
        }

        if faculty_name not in faculties:
            faculties[faculty_name] = []
        faculties[faculty_name].append(course_data)

    with open(output_file, 'w') as f:
        json.dump(faculties, f, indent=4)

    print(f"Successfully scraped {sum(len(courses) for courses in faculties.values())} courses across {len(faculties)} faculties.")
    print(f"Data saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape university requirements from universityqualifications.co.za")
    parser.add_argument("--url", default="https://universityqualifications.co.za/universities/university-of-the-witwatersrand/programmes", help="URL of the university programmes page")
    parser.add_argument("--output", default="wits_scraped_data.json", help="Output JSON file path")
    args = parser.parse_args()

    scrape_university(args.url, args.output)
