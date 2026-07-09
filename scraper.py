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
            if "year" in text.lower() or text.isdigit():
                duration_match = re.search(r'\d+', text)
                if duration_match:
                    duration = duration_match.group()
            elif "APS:" in text:
                aps_parts = text.split(":")
                if len(aps_parts) > 1:
                    aps = aps_parts[1].strip()
            elif "APS" in text:
                aps_match = re.search(r'APS\s+(.*)', text, re.IGNORECASE)
                if aps_match:
                    aps = aps_match.group(1).strip()

        # Extract Key Requirements
        requirements = []
        req_header = card.find(lambda tag: tag.name == 'p' and "Key Requirements" in tag.get_text())
        if req_header:
            req_text_tag = req_header.find_next_sibling()
            if req_text_tag:
                req_text = req_text_tag.get_text(strip=True)
                if req_text.startswith("Show full requirements"):
                    req_text = req_text[len("Show full requirements"):].strip()

                # Basic Parsing of subjects: "Subject X(Y%+), Subject Z(Level)"
                # The user noted that splitting "OR" inside subjects like "English Home Language OR First Additional Language"
                # broke the frontend because it created "English Home Language (Level 6) (70)" and "First Additional Language (Level 6) (70)"
                # and the user failed because they didn't have "First Additional Language".

                # Separate out dot delimited sentences since sometimes APS is mentioned in the same line
                sentences = re.split(r'\.\s*', req_text)

                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence: continue

                    # We should not skip the entire sentence if "minimum aps" is in it,
                    # because it might be a comma separated list like:
                    # "English level 4, minimum aps is 22"

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

                        def clean_subject(subj):
                            subj = subj.strip()
                            if subj.endswith(':'): subj = subj[:-1].strip()
                            if subj.lower().startswith('or '): subj = subj[3:].strip()
                            prefixes_to_remove = ["compulsory subjects:", "compulsory subject:", "recommended subjects:", "recommended subject:"]
                            for prefix in prefixes_to_remove:
                                if subj.lower().startswith(prefix):
                                    subj = subj[len(prefix):].strip()
                            return subj

                        # Handle APS embedded in text
                        if "aps is " in part.lower() or "minimum aps " in part.lower() or "aps of " in part.lower():
                            continue

                        # Pattern 1: Subject Level(Percentage%+) e.g., Mathematics 5(60%+)
                        # Or Subject Code 4, Subject 6, Subject 5/FAL 6
                        match_paren = re.search(r'^(.*?)\s*\(\s*(?:Minimum Admission )?(?:Level|Code)?\s*(\d+)\s*\)$', part, re.IGNORECASE)
                        if match_paren:
                            subject = clean_subject(match_paren.group(1))
                            level = match_paren.group(2)
                            requirements.append({"subject": subject, "level": level, "percentage": ""})
                        else:
                            # Pattern 2: Subject: Level X or Subject: X
                            match_level = re.search(r'(.*?):\s*(?:Code|Level\s*)?(\d+|null)', part, re.IGNORECASE)
                            if match_level and "minimum" not in part.lower():
                                subject = match_level.group(1).strip()
                                if subject.endswith(':'): subject = subject[:-1].strip()
                                level = match_level.group(2)
                                if level.lower() != 'null':
                                    requirements.append({"subject": subject, "level": level})
                            match = re.search(r'(.*?)\s+(?:minimum )?(?:Code|Level)?\s*(\d+)(?:\s*\(?(\d+)%?\+?\)?|\s*/.*?)?$', part, re.IGNORECASE)
                            if match and ("minimum" not in part.lower() or ("minimum" in part.lower() and "level" in part.lower())):
                                subject = clean_subject(match.group(1))
                                level = match.group(2)
                                percentage = match.group(3) if match.group(3) else ""

                                requirements.append({"subject": subject, "level": level, "percentage": percentage})
                            else:
                                # Pattern 2: Subject: Level X or Subject: X
                                match_level = re.search(r'(.*?):\s*(?:minimum )?(?:Code|Level\s*)?(\d+|null)', part, re.IGNORECASE)
                                if match_level and ("minimum" not in part.lower() or ("minimum" in part.lower() and "level" in part.lower())):
                                    subject = clean_subject(match_level.group(1))
                                    level = match_level.group(3) if len(match_level.groups()) >= 3 else match_level.group(2)
                                    if level.lower() != 'null':
                                        requirements.append({"subject": subject, "level": level, "percentage": ""})
                                else:
                                    if "minimum of" in part.lower() or part.lower().strip() == "minimum":
                                        continue
                                    subject = clean_subject(part)
                                    # Fallback just keep the string
                                    requirements.append({"subject": subject, "level": "", "percentage": ""})

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
