import json

def fix_data():
    with open('universities/stellenbosch/data.json', 'r') as f:
        data = json.load(f)

    for faculty, courses in data.items():
        for course in courses:
            reqs = course.get('required_subjects', [])
            for i, req in enumerate(reqs):
                if req.get('level') == "" and req.get('percentage') == "":
                    # Look ahead or behind for a percentage
                    # Usually it's "OR English", then "OR Afrikaans" with percentage "50"

                    # Look ahead
                    found = False
                    for j in range(i+1, len(reqs)):
                        if reqs[j].get('percentage') or reqs[j].get('level'):
                            if reqs[j].get('subject', '').startswith('OR '):
                                req['percentage'] = reqs[j].get('percentage')
                                req['level'] = reqs[j].get('level')
                                found = True
                                break
                            else:
                                break

                    # If not found ahead, look behind?
                    if not found:
                        for j in range(i-1, -1, -1):
                            if reqs[j].get('percentage') or reqs[j].get('level'):
                                if req.get('subject', '').startswith('OR '):
                                    req['percentage'] = reqs[j].get('percentage')
                                    req['level'] = reqs[j].get('level')
                                    found = True
                                    break
                                else:
                                    break

    with open('universities/stellenbosch/data.json', 'w') as f:
        json.dump(data, f, indent=4)

if __name__ == '__main__':
    fix_data()
