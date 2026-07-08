import requests
from bs4 import BeautifulSoup
import json
import re
import argparse

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
                parts = req_text.split(',')
                for part in parts:
                    part = part.strip()
                    if not part: continue

                    # Try to handle separated alternative subjects if they contain " OR "
                    sub_parts = [part] # We'll keep them together as requested in memory for some formats, but let's check

                    # Pattern 1: Subject Level(Percentage%+) e.g., Mathematics 5(60%+)
                    match = re.search(r'(.*?)\s+(\d+)\s*\(?(\d+)%?\+?\)?', part)
                    if match:
                        subject = match.group(1).strip()
                        level = match.group(2)
                        percentage = match.group(3)
                        requirements.append({"subject": subject, "level": level, "percentage": percentage})
                    else:
                        # Pattern 2: Subject: Level X or Subject: X
                        match_level = re.search(r'(.*?):\s*(Level\s*)?(\d+|null)', part, re.IGNORECASE)
                        if match_level:
                            subject = match_level.group(1).strip()
                            level = match_level.group(3)
                            if level.lower() != 'null':
                                requirements.append({"subject": subject, "level": level})
                        else:
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
