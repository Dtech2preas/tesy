import json
import os

universities = [
    {"file": "stellenbosch.json", "name": "Stellenbosch University", "html": "stellenbosch.html"},
    {"file": "tut.json", "name": "Tshwane University of Technology (TUT)", "html": "tut.html"},
    {"file": "uct.json", "name": "University of Cape Town (UCT)", "html": "uct.html"},
    {"file": "ul.json", "name": "University of Limpopo (UL)", "html": "ul.html"},
    {"file": "ump.json", "name": "University of Mpumalanga (UMP)", "html": "ump.html"},
    {"file": "univen.json", "name": "University of Venda (Univen)", "html": "univen.html"},
    {"file": "up.json", "name": "University of Pretoria (UP)", "html": "up.html"},
    {"file": "wits.json", "name": "University of the Witwatersrand (Wits)", "html": "wits.html"}
]

template = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{uni_name} Courses & Eligibility</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #ccc; padding-bottom: 10px; margin-bottom: 20px; }}
        .back-btn {{ text-decoration: none; padding: 10px 15px; background: #333; color: #fff; border-radius: 5px; }}
        .search-bar {{ width: 100%; padding: 10px; font-size: 16px; margin-bottom: 20px; box-sizing: border-box; }}
        .course-card {{ border: 1px solid #ddd; padding: 15px; margin-bottom: 15px; border-radius: 5px; background: #fafafa; }}
        .course-title {{ font-size: 18px; font-weight: bold; margin-bottom: 10px; color: #0056b3; }}
        .likelihood-100 {{ color: #28a745; font-weight: bold; font-size: 1.1em; }}
        .likelihood-high {{ color: #85c100; font-weight: bold; font-size: 1.1em; }}
        .likelihood-med {{ color: #fd7e14; font-weight: bold; font-size: 1.1em; }}
        .likelihood-low {{ color: #dc3545; font-weight: bold; font-size: 1.1em; }}
        .faculty-header {{ margin-top: 30px; margin-bottom: 15px; background: #e9ecef; padding: 10px; border-radius: 4px; }}
        .req-list {{ margin: 5px 0 0 20px; }}
        .course-details {{ color: #555; font-size: 0.9em; margin-bottom: 10px; }}
        .likelihood-box {{ background: #fff; border: 1px solid #eee; padding: 10px; border-radius: 5px; margin-top: 10px; }}
    </style>
</head>
<body>

    <div class="header">
        <h1>{uni_name}</h1>
        <a href="index.html" class="back-btn">&larr; Back to Subjects</a>
    </div>

    <div id="user-info" style="margin-bottom: 20px; padding: 15px; background: #eef; border-radius: 5px;">
        Loading your subjects...
    </div>

    <input type="text" id="search-input" class="search-bar" placeholder="Search for a course..." onkeyup="filterCourses()">

    <div id="courses-container">
        Loading courses...
    </div>

    <script>
        const uniFile = '{uni_file}';
        let allCourses = [];
        let userMarks = [];
        let userAps = 0;
        let userFps = 0;
        let helperData = null;

        async function init() {{
            const marksStr = localStorage.getItem('userMarks');
            if (!marksStr) {{
                document.getElementById('courses-container').innerHTML = '<p style="color:red; font-weight:bold;">No subjects found. Please go back to the main page and enter your subjects first.</p>';
                document.getElementById('user-info').style.display = 'none';
                return;
            }}
            userMarks = JSON.parse(marksStr);
            userAps = parseInt(localStorage.getItem('userAps') || '0', 10);
            userFps = parseInt(localStorage.getItem('userFps') || '0', 10);

            let helperStr = localStorage.getItem('subjectHelper');
            if (helperStr) {{
                helperData = JSON.parse(helperStr);
            }} else {{
                // fallback fetch
                try {{
                    let hRes = await fetch('helper.json');
                    helperData = await hRes.json();
                }} catch(e) {{
                    console.log("Could not load helper.json", e);
                }}
            }}

            let subStrings = userMarks.map(m => `<li>${{m.subject}}: ${{m.percentage}}% (Level ${{m.level}})</li>`).join('');
            document.getElementById('user-info').innerHTML = `
                <div style="display: flex; justify-content: space-between;">
                    <div>
                        <strong>Your APS:</strong> ${{userAps}} <br>
                        <strong>Your FPS:</strong> ${{userFps}} (Total percentage)
                    </div>
                    <div>
                        <ul style="margin: 0; padding-left: 20px;">${{subStrings}}</ul>
                    </div>
                </div>
            `;

            try {{
                const response = await fetch(uniFile);
                if (!response.ok) throw new Error('File not found');
                const data = await response.json();
                renderCourses(data);
            }} catch(err) {{
                document.getElementById('courses-container').innerHTML = '<p style="color:red">Failed to load university data. Ensure you are running this through a local server.</p>';
                console.error(err);
            }}
        }}

        function checkSubjectMatch(reqSubjectName, userMarks, helperData) {{
            if (!reqSubjectName) return null;
            let reqLower = reqSubjectName.toLowerCase().trim();

            let matchedMainSubject = null;

            if (helperData) {{
                for (const mainSub in helperData) {{
                    let altFound = false;
                    for (const altName of helperData[mainSub]) {{
                        let altLower = altName.toLowerCase().trim();
                        if (reqLower === altLower) {{
                            matchedMainSubject = mainSub;
                            altFound = true;
                            break;
                        }}
                    }}
                    if (altFound) break;
                }}

                if (!matchedMainSubject) {{
                    for (const mainSub in helperData) {{
                        let altFound = false;
                        for (const altName of helperData[mainSub]) {{
                            let altLower = altName.toLowerCase().trim();
                            if (reqLower.includes(altLower) || altLower.includes(reqLower)) {{
                                if (reqLower.includes("literacy") && !altLower.includes("literacy")) continue;
                                if (altLower.includes("literacy") && !reqLower.includes("literacy")) continue;
                                if (reqLower.includes("technical") && !altLower.includes("technical")) continue;
                                if (altLower.includes("technical") && !reqLower.includes("technical")) continue;

                                matchedMainSubject = mainSub;
                                altFound = true;
                                break;
                            }}
                        }}
                        if (altFound) break;
                    }}
                }}
            }}

            if (!matchedMainSubject) {{
                matchedMainSubject = reqSubjectName;
            }}

            let bestMark = null;

            for (let mark of userMarks) {{
                let markLower = mark.subject.toLowerCase().trim();
                let markMainSubject = null;

                if (helperData) {{
                    for (const mainSub in helperData) {{
                        let altFound = false;
                        for (const altName of helperData[mainSub]) {{
                            if (markLower === altName.toLowerCase().trim()) {{
                                markMainSubject = mainSub;
                                altFound = true;
                                break;
                            }}
                        }}
                        if (altFound) break;
                    }}
                }}

                if (!markMainSubject) {{
                    markMainSubject = mark.subject;
                }}

                if (markMainSubject === matchedMainSubject) {{
                    if (!bestMark || mark.percentage > bestMark.percentage) {{
                        bestMark = mark;
                    }}
                }}
            }}

            if (bestMark) return bestMark;

            for (let mark of userMarks) {{
                let markLower = mark.subject.toLowerCase().trim();
                if (reqLower === markLower) return mark;

                if (reqLower.includes(markLower) || markLower.includes(reqLower)) {{
                    if (reqLower.includes("literacy") && !markLower.includes("literacy")) continue;
                    if (markLower.includes("literacy") && !reqLower.includes("literacy")) continue;
                    if (reqLower.includes("technical") && !markLower.includes("technical")) continue;
                    if (markLower.includes("technical") && !reqLower.includes("technical")) continue;
                    return mark;
                }}
            }}

            return null;
        }}

        function calculateLikelihood(course, userMarks, userAps, userFps, helperData) {{
            const levelToMinPercent = (level) => {{
                const map = {{ 1: 0, 2: 30, 3: 40, 4: 50, 5: 60, 6: 70, 7: 80 }};
                return map[level] || 50;
            }};

            const getMinForRequirement = (req) => {{
                if (typeof req === 'object' && req !== null) {{
                    if (req.minPercent !== undefined) return req.minPercent;
                    if (req.minLevel !== undefined) return levelToMinPercent(req.minLevel);
                    if (req.percentage !== undefined) {{
                        let percMatch = String(req.percentage).match(/(\d+)%/);
                        if (percMatch) return parseInt(percMatch[1]);
                        let num = parseInt(String(req.percentage).replace(/[^0-9]/g, ''), 10);
                        if (!isNaN(num)) return num;
                    }}
                    if (req.level !== undefined && req.level !== "Unspecified") {{
                        let lvl = parseInt(req.level);
                        if (lvl > 7) return lvl; // It's actually a percentage
                        return levelToMinPercent(lvl);
                    }}
                }}
                const levelMatch = String(req).match(/Level\s*(\d)/i);
                if (levelMatch) return levelToMinPercent(parseInt(levelMatch[1]));
                const percentMatch = String(req).match(/(\d+)%/);
                if (percentMatch) return parseInt(percentMatch[1]);
                return 50;
            }};

            let hardFailReason = null;

            if (course.required_subjects && Array.isArray(course.required_subjects)) {{
                // Need to group ORs as before or assume course.required_subjects are individual objects
                // In the old code we grouped ORs. The new code assumes course.required_subjects might have arrays for ORs
                // Let's adapt the user's logic to group ORs similar to old logic first so we have the arrays.

                let groupedReqs = [];
                let currentGroup = [];
                for (let i = 0; i < course.required_subjects.length; i++) {{
                    let req = course.required_subjects[i];
                    if (!req.subject || req.subject.toLowerCase().includes('additional subject') || req.subject.toLowerCase().includes('other subject')) continue;

                    let sLower = req.subject.toLowerCase().trim();
                    if (sLower.startsWith('or ') || sLower.includes(' or ')) {{
                        if (sLower.startsWith('or ')) {{
                            req.subject = req.subject.substring(3).trim();
                        }}
                        if (currentGroup.length === 0 && groupedReqs.length > 0) {{
                            groupedReqs[groupedReqs.length - 1].push(req);
                        }} else {{
                            currentGroup.push(req);
                        }}
                    }} else {{
                        if (currentGroup.length > 0) {{
                            groupedReqs.push(currentGroup);
                        }}
                        currentGroup = [req];
                    }}
                }}
                if (currentGroup.length > 0) {{
                    groupedReqs.push(currentGroup);
                }}

                let mergedGroups = [];
                for (let grp of groupedReqs) {{
                    if (mergedGroups.length > 0) {{
                        let lastGrp = mergedGroups[mergedGroups.length - 1];
                        let isMath1 = grp[0].subject.toLowerCase().includes('math');
                        let isMath2 = lastGrp[0].subject.toLowerCase().includes('math');
                        let isEng1 = grp[0].subject.toLowerCase().includes('english');
                        let isEng2 = lastGrp[0].subject.toLowerCase().includes('english');

                        if ((isMath1 && isMath2) || (isEng1 && isEng2)) {{
                            lastGrp.push(...grp);
                        }} else {{
                            mergedGroups.push(grp);
                        }}
                    }} else {{
                        mergedGroups.push(grp);
                    }}
                }}

                for (let group of mergedGroups) {{
                    let isGarbage = false;
                    for (let req of group) {{
                        if (typeof req.subject === 'string' && (req.subject.includes('NSC/IEB') || req.subject.includes('Minimum requirements'))) {{
                            isGarbage = true;
                        }}
                    }}
                    if (isGarbage) continue;

                    let passedOr = false;
                    for (let subj of group) {{
                        const subjectName = typeof subj === 'object' ? subj.subject || subj : subj;
                        const matchedUserMark = checkSubjectMatch(subjectName, userMarks, helperData);

                        if (matchedUserMark !== null) {{
                            const minPct = getMinForRequirement(subj);
                            // minPct could be 0 if unspecified, we should pass it
                            if (minPct === 0 || matchedUserMark.percentage >= minPct - 15) {{
                                passedOr = true;
                                break;
                            }}
                        }} else if (getMinForRequirement(subj) === 0) {{
                            // No minimum requirement specified, implicitly pass if matched?
                            // Or rather, if no minimum is specified, they still need the subject. But if they don't have it, they fail.
                        }}
                    }}

                    if (!passedOr) {{
                        const subjNames = group.map(s => s.subject).join(' or ');
                        hardFailReason = `Missing or significantly below required subject(s): ${{subjNames}}`;
                        return {{ likelihood: 0, status: "ineligible", reason: hardFailReason }};
                    }}
                }}
                course._mergedGroups = mergedGroups; // save for stage 2
            }}

            let minScore = null;
            let userScore = null;
            let maxSpread = 8.0;
            let scoreName = "";

            if (course.aps !== undefined || course.aps_range !== undefined) {{
                minScore = course.aps !== undefined ? parseInt(course.aps, 10) : parseInt(String(course.aps_range).split('-')[0], 10);
                if (isNaN(minScore) || minScore === 0) minScore = null;
            }}

            if (minScore !== null) {{
                userScore = Math.min(userAps, 42); // Cap APS at 42
                maxSpread = 8.0;
                scoreName = "APS";
            }} else if (course.fps !== undefined) {{
                minScore = parseInt(course.fps, 10);
                if (!isNaN(minScore) && minScore > 0) {{
                    userScore = userFps;
                    maxSpread = 80.0;
                    scoreName = "FPS";
                }} else {{
                    minScore = null;
                }}
            }}

            let likelihood;
            let status = "eligible";
            let reason = `Strong match – ${{scoreName}} strength and subject performance`;

            if (minScore === null) {{
                likelihood = 70;
                reason = "Meets all published requirements";
            }} else {{
                const relative = (userScore - minScore) / maxSpread;
                let strength = Math.max(0, Math.min(100, 50 + relative * 50));

                let avgSubjectScore = 100;
                if (course._mergedGroups && course._mergedGroups.length > 0) {{
                    let subjectScores = [];
                    for (let group of course._mergedGroups) {{
                        let isGarbage = false;
                        for (let req of group) {{
                            if (typeof req.subject === 'string' && (req.subject.includes('NSC/IEB') || req.subject.includes('Minimum requirements'))) {{
                                isGarbage = true;
                            }}
                        }}
                        if (isGarbage) continue;

                        let bestExcess = 0;
                        let hasMinRequirement = false;

                        for (let subj of group) {{
                            const subjectName = typeof subj === 'object' ? subj.subject || subj : subj;
                            const matchedUserMark = checkSubjectMatch(subjectName, userMarks, helperData);

                            const minPct = getMinForRequirement(subj);
                            if (minPct > 0) hasMinRequirement = true;

                            if (matchedUserMark !== null && minPct > 0) {{
                                const excess = ((matchedUserMark.percentage - minPct) / (100 - minPct)) * 100;
                                bestExcess = Math.max(bestExcess, Math.max(0, Math.min(100, excess)));
                            }} else if (matchedUserMark !== null && minPct === 0) {{
                                bestExcess = 100;
                            }}
                        }}
                        if (hasMinRequirement) {{
                            subjectScores.push(bestExcess);
                        }} else {{
                            subjectScores.push(100);
                        }}
                    }}
                    if (subjectScores.length > 0) {{
                        avgSubjectScore = subjectScores.reduce((a, b) => a + b, 0) / subjectScores.length;
                    }}
                }}

                likelihood = Math.round(0.6 * avgSubjectScore + 0.4 * strength);
                likelihood = Math.max(5, Math.min(100, likelihood));

                if (userScore < minScore) {{
                    const diff = minScore - userScore;
                    reason = `Slightly below minimum ${{scoreName}} (by ${{diff}} points) – low but possible chance`;
                }}
            }}

            return {{ likelihood: Math.round(likelihood), status, reason }};
        }}

        function getLikelihoodClass(percent) {{
            if (percent === 100) return 'likelihood-100';
            if (percent >= 70) return 'likelihood-high';
            if (percent >= 40) return 'likelihood-med';
            return 'likelihood-low';
        }}

        function renderCourses(data) {{
            const container = document.getElementById('courses-container');
            container.innerHTML = '';
            allCourses = [];

            let faculties = Object.keys(data);

            faculties.forEach(faculty => {{
                let facDiv = document.createElement('div');
                facDiv.className = 'faculty-section';

                let facHead = document.createElement('h2');
                facHead.className = 'faculty-header';
                facHead.textContent = faculty;
                facDiv.appendChild(facHead);

                let courseList = data[faculty];
                if (!Array.isArray(courseList)) return;

                courseList.forEach(course => {{
                    let cDiv = document.createElement('div');
                    cDiv.className = 'course-card';

                    let likelihood = calculateLikelihood(course, userMarks, userAps, userFps, helperData);

                    let reqsHtml = '';
                    if (course.required_subjects && course.required_subjects.length > 0) {{
                        let subs = course.required_subjects.map(s => {{
                            if (!s.subject) return '';
                            let reqStr = s.subject;
                            if (s.level && s.level !== "Unspecified") reqStr += ` (Level ${{s.level}})`;
                            if (s.percentage) reqStr += ` (${{s.percentage}})`;
                            return `<li>${{reqStr}}</li>`;
                        }}).filter(str => str !== '').join('');
                        reqsHtml = subs ? `<ul class="req-list">${{subs}}</ul>` : 'None specified.';
                    }} else {{
                        reqsHtml = `<p style="margin: 5px 0 0 0;">None specified.</p>`;
                    }}

                    let scoreHtml = [];
                    if (course.aps) scoreHtml.push(`<strong>APS:</strong> ${{course.aps}}`);
                    if (course.aps_range) scoreHtml.push(`<strong>APS:</strong> ${{course.aps_range}}`);
                    if (course.fps) scoreHtml.push(`<strong>FPS:</strong> ${{course.fps}}`);

                    let detailsHtml = scoreHtml.length > 0 ? scoreHtml.join(' | ') : '<strong>APS:</strong> Not specified';
                    if (course.duration) detailsHtml += ` | <strong>Duration:</strong> ${{course.duration}} years`;
                    if (course.course_code) detailsHtml += ` | <strong>Code:</strong> ${{course.course_code}}`;

                    cDiv.innerHTML = `
                        <div class="course-title">${{course.course_name}}</div>
                        <div class="course-details">${{detailsHtml}}</div>
                        <div><strong>Required Subjects:</strong></div>
                        ${{reqsHtml}}

                        <div class="likelihood-box">
                            <strong>Likelihood of Acceptance: </strong>
                            <span class="${{getLikelihoodClass(likelihood.likelihood)}}">${{likelihood.likelihood}}%</span>
                            <div style="font-size: 0.9em; color: #666; margin-top: 5px;">${{likelihood.reason}}</div>
                        </div>
                    `;

                    allCourses.push({{
                        name: course.course_name.toLowerCase(),
                        element: cDiv,
                        parent: facDiv
                    }});

                    facDiv.appendChild(cDiv);
                }});

                if (facDiv.querySelectorAll('.course-card').length > 0) {{
                    container.appendChild(facDiv);
                }}
            }});
        }}

        function filterCourses() {{
            let filter = document.getElementById('search-input').value.toLowerCase();

            document.querySelectorAll('.faculty-header').forEach(el => el.style.display = 'none');

            allCourses.forEach(c => {{
                if (c.name.includes(filter)) {{
                    c.element.style.display = 'block';
                    c.parent.querySelector('.faculty-header').style.display = 'block';
                }} else {{
                    c.element.style.display = 'none';
                }}
            }});
        }}

        window.onload = init;
    </script>
</body>
</html>
"""

for uni in universities:
    with open(uni['html'], 'w') as f:
        f.write(template.format(uni_name=uni['name'], uni_file=uni['file']))
    print(f"Generated {uni['html']}")
