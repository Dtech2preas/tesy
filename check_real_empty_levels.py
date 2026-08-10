import json

def is_garbage(s):
    s = s.lower()
    garbage = [
        "and comply with", "combination", "interview", "portfolio",
        "audition", "selection considers", "economic status", "motivational letter",
        "a limited number of applicants", "(if you take", "(if you choose", "(if you wish"
    ]
    for g in garbage:
        if g in s:
            return True
    return False

def check_empty_levels():
    with open('universities/stellenbosch/data.json', 'r') as f:
        data = json.load(f)

    empty_levels = []

    for faculty, courses in data.items():
        for course in courses:
            for req in course.get('required_subjects', []):
                subj = req.get('subject', '')
                if is_garbage(subj):
                    continue
                if req.get('level') == "" and req.get('percentage') == "":
                    empty_levels.append({
                        'course': course.get('course_name'),
                        'subject': subj,
                        'rawRequirements': course.get('rawRequirements')
                    })

    if empty_levels:
        print(f"Found {len(empty_levels)} non-garbage subjects with empty level AND empty percentage:")
        for m in empty_levels[:15]:
            print(f" - {m['course']} | Subject: {m['subject']}")
    else:
        print("All real required subjects have either a level or a percentage.")

if __name__ == '__main__':
    check_empty_levels()
