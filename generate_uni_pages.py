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

# Fixing double-bracket escaping for python string.format()
template = """<!DOCTYPE html>
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

        function checkSubjectMatch(reqSubjectName) {{
            if (!reqSubjectName) return null;
            let reqLower = reqSubjectName.toLowerCase().trim();
            for (let mark of userMarks) {{
                let markLower = mark.subject.toLowerCase().trim();

                if (reqLower.includes(markLower) || markLower.includes(reqLower)) return mark;
                if ((reqLower.includes('maths') || reqLower.includes('mathematics')) && (markLower.includes('maths') || markLower.includes('mathematics'))) return mark;
                if (reqLower.includes('english') && markLower.includes('english')) return mark;
                if ((reqLower.includes('phys sci') || reqLower.includes('physical sciences')) && (markLower.includes('phys sci') || markLower.includes('physical sciences'))) return mark;
                if ((reqLower.includes('life sci') || reqLower.includes('biology')) && (markLower.includes('life sci') || markLower.includes('biology'))) return mark;
            }}
            return null;
        }}

        function calculateLikelihood(course) {{
            let MAX_APS = 42;
            let reqAps = parseInt(course.aps || '0', 10);
            let reqFps = parseInt(course.fps || '0', 10);

            if (course.aps_range) {{
                let parts = course.aps_range.split('-');
                if (parts.length > 0) reqAps = parseInt(parts[0], 10);
            }}

            let isFps = (reqFps > 0 && reqAps === 0);
            let targetScore = isFps ? reqFps : reqAps;
            let userScore = isFps ? userFps : userAps;

            let meetsSubjects = true;
            let subjectFails = [];

            let totalUserPerc = 0;
            let totalMinPerc = 0;
            let validSubjectCount = 0;

            if (course.required_subjects && course.required_subjects.length > 0) {{
                for (let req of course.required_subjects) {{
                    // Skip 'Additional Subjects' or empty ones
                    if (!req.subject || req.subject.toLowerCase() === 'additional subjects') continue;

                    validSubjectCount++;
                    let matchedMark = checkSubjectMatch(req.subject);

                    let reqLevel = parseInt(req.level || '0', 10);
                    if (isNaN(reqLevel) || req.level === "Unspecified") reqLevel = 0;

                    let reqPercStr = req.percentage || '';
                    let reqPerc = 0;
                    if (reqPercStr) {{
                        if (reqPercStr.includes('-')) {{
                            reqPerc = parseInt(reqPercStr.split('-')[0], 10);
                        }} else {{
                            reqPerc = parseInt(reqPercStr.replace(/[^0-9]/g, ''), 10);
                        }}
                    }}
                    if (isNaN(reqPerc)) reqPerc = 0;

                    totalMinPerc += reqPerc;

                    if (!matchedMark) {{
                        meetsSubjects = false;
                        subjectFails.push(`Missing: ${{req.subject}}`);
                        // Use 0 for user percentage
                        continue;
                    }}

                    totalUserPerc += matchedMark.percentage;

                    if (reqLevel > 0 && matchedMark.level < reqLevel) {{
                        meetsSubjects = false;
                        subjectFails.push(`${{req.subject}} (Need L${{reqLevel}}, Got L${{matchedMark.level}})`);
                    }} else if (reqPerc > 0 && matchedMark.percentage < reqPerc) {{
                        meetsSubjects = false;
                        subjectFails.push(`${{req.subject}} (Need ${{reqPerc}}%, Got ${{matchedMark.percentage}}%)`);
                    }}
                }}
            }}

            let avgUserPerc = validSubjectCount > 0 ? (totalUserPerc / validSubjectCount) : (isFps ? userScore : 100);
            let avgMinPerc = validSubjectCount > 0 ? (totalMinPerc / validSubjectCount) : (isFps ? targetScore : 0);

            let meetsTargetScore = false;
            if (targetScore === 0) {{
                meetsTargetScore = true;
            }} else {{
                meetsTargetScore = (userScore >= targetScore);
            }}

            let meetsAllMinimums = meetsSubjects && meetsTargetScore;

            let rawScore = 0;
            let rawMin = 0;

            if (!isFps) {{
                // Standard APS logic
                rawScore = ((userAps / MAX_APS) * 100) * 0.65 + (avgUserPerc) * 0.35;
                rawMin = ((reqAps / MAX_APS) * 100) * 0.65 + (avgMinPerc) * 0.35;
            }} else {{
                // FPS only (no APS)
                rawScore = avgUserPerc;
                rawMin = avgMinPerc;
            }}

            let mappedScore = 0;

            if (meetsAllMinimums) {{
                if (rawMin >= 100) {{
                    mappedScore = 100;
                }} else {{
                    mappedScore = 50 + ((rawScore - rawMin) / (100 - rawMin)) * 50;
                }}
            }} else {{
                if (rawMin <= 0) {{
                    mappedScore = 0;
                }} else {{
                    mappedScore = (rawScore / rawMin) * 49;
                    mappedScore = Math.min(mappedScore, 49);
                }}
            }}

            // Clamp score
            mappedScore = Math.max(0, Math.min(100, Math.round(mappedScore)));

            let reason = "";
            let scoreType = isFps ? "FPS" : "APS";

            if (meetsAllMinimums) {{
                reason = `Met all requirements! Your score reflects how far above the minimums you are.`;
            }} else {{
                let parts = [];
                if (subjectFails.length > 0) parts.push(`Failed subjects: ${{subjectFails.join(', ')}}`);
                if (!meetsTargetScore) parts.push(`Your ${{scoreType}} (${{userScore}}) is below required (${{targetScore}})`);
                reason = parts.join('. ');
            }}

            return {{ percent: mappedScore, reason: reason }};
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

            // Handle UMP structure differences
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

                    let likelihood = calculateLikelihood(course);

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
                            <span class="${{getLikelihoodClass(likelihood.percent)}}">${{likelihood.percent}}%</span>
                            <div style="font-size: 0.9em; color: #666; margin-top: 5px;">${{likelihood.reason}}</div>
                        </div>
                    `;

                    // Store elements and course data for search filtering
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

            // Hide all faculty headers first
            document.querySelectorAll('.faculty-header').forEach(el => el.style.display = 'none');

            allCourses.forEach(c => {{
                if (c.name.includes(filter)) {{
                    c.element.style.display = 'block';
                    // Show parent header
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
