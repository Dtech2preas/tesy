import json
import re

def fix_data():
    with open('universities/stellenbosch/data.json', 'r') as f:
        data = json.load(f)

    for faculty, courses in data.items():
        for course in courses:
            reqs = course.get('required_subjects', [])
            for i, req in enumerate(reqs):
                if req.get('level') == "" and req.get('percentage') == "":
                    # Check if there is a percentage embedded in the subject itself
                    subj = req.get('subject', '')
                    m = re.search(r'(\d+)%', subj)
                    if m:
                        req['percentage'] = m.group(1)

    with open('universities/stellenbosch/data.json', 'w') as f:
        json.dump(data, f, indent=4)

if __name__ == '__main__':
    fix_data()
