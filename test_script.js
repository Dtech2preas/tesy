function testLogic() {
    let MAX_APS = 42;
    // user data - student missing a subject
    let userMarks = [
        {subject: "English", percentage: 60, level: 5}
    ];
    let userAps = 25;
    let userFps = 300;

    let course = {
        aps: "20",
        fps: "",
        required_subjects: [
            {subject: "Mathematics", percentage: "50", level: "4"},
            {subject: "English", percentage: "50", level: "4"}
        ]
    };

    // Mock helperData for testing
    let helperData = {
        "Mathematics": ["Mathematics", "Maths", "Maths Lit"], // just a mock
        "English": ["English", "Engl"]
    };

    function checkSubjectMatch(reqSubjectName) {
        if (!reqSubjectName) return null;
        let reqLower = reqSubjectName.toLowerCase().trim();

        // Math logic: if both requirement and user mark are some form of math, it matches
        let reqIsSomeMath = reqLower.includes('math') || reqLower.includes('mathematics') || reqLower.includes('technical math') || reqLower.includes('mathematical lit');
        if (reqIsSomeMath) {
            for (let mark of userMarks) {
                let markLower = mark.subject.toLowerCase().trim();
                let markIsSomeMath = markLower.includes('math') || markLower.includes('mathematics') || markLower.includes('technical math') || markLower.includes('mathematical lit');
                if (markIsSomeMath) return mark;
            }
        }

        // First pass: Direct exact or subset match
        for (let mark of userMarks) {
            let markLower = mark.subject.toLowerCase().trim();
            if (reqLower === markLower || markLower.includes(reqLower) || reqLower.includes(markLower)) {
                // Check literacy
                if (reqLower.includes("literacy") && !markLower.includes("literacy")) continue;
                if (markLower.includes("literacy") && !reqLower.includes("literacy")) continue;
                return mark;
            }
        }

        // Second pass: Use helperData
        if (helperData) {
            let matchedMainSubject = null;
            for (const mainSub in helperData) {
                for (const altName of helperData[mainSub]) {
                    let altLower = altName.toLowerCase().trim();
                    if (reqLower === altLower || reqLower.includes(altLower) || altLower.includes(reqLower)) {
                        if (reqLower.includes("literacy") && !altLower.includes("literacy")) continue;
                        if (altLower.includes("literacy") && !reqLower.includes("literacy")) continue;

                        matchedMainSubject = mainSub;
                        break;
                    }
                }
                if (matchedMainSubject) break;
            }

            if (matchedMainSubject) {
                let mainSubLower = matchedMainSubject.toLowerCase().trim();
                for (let mark of userMarks) {
                    let markLower = mark.subject.toLowerCase().trim();
                    if (markLower === mainSubLower || markLower.includes(mainSubLower)) {
                        if (markLower.includes("literacy") && !mainSubLower.includes("literacy")) continue;
                        if (mainSubLower.includes("literacy") && !markLower.includes("literacy")) continue;

                        return mark;
                    }
                }
            }
        }

        // Fallbacks
        for (let mark of userMarks) {
            let markLower = mark.subject.toLowerCase().trim();
            if ((reqLower.includes('maths') || reqLower.includes('mathematics')) && !reqLower.includes('lit') && (markLower.includes('maths') || markLower.includes('mathematics')) && !markLower.includes('lit')) return mark;
            if ((reqLower.includes('math') && reqLower.includes('lit')) && (markLower.includes('math') && markLower.includes('lit'))) return mark;
            if (reqLower.includes('english') && markLower.includes('english')) return mark;
            if ((reqLower.includes('phys sci') || reqLower.includes('physical sciences')) && (markLower.includes('phys sci') || markLower.includes('physical sciences'))) return mark;
            if ((reqLower.includes('life sci') || reqLower.includes('biology')) && (markLower.includes('life sci') || markLower.includes('biology'))) return mark;
        }
        return null;
    }

    let reqAps = parseInt(course.aps || '0', 10);
    let reqFps = parseInt(course.fps || '0', 10);

    if (course.aps_range) {
        let parts = course.aps_range.split('-');
        if (parts.length > 0) reqAps = parseInt(parts[0], 10);
    }

    // isFps should be true if course.fps exists and course.aps does not exist
    let isFps = (reqFps > 0 && reqAps === 0);
    let targetScore = isFps ? reqFps : reqAps;
    let userScore = isFps ? userFps : userAps;

    let meetsSubjects = true;
    let subjectFails = [];

    let totalUserPerc = 0;
    let totalMinPerc = 0;
    let validSubjectCount = 0;

    if (course.required_subjects && course.required_subjects.length > 0) {
        for (let req of course.required_subjects) {
            // Skip 'Additional Subjects' or empty ones
            if (!req.subject || req.subject.toLowerCase().includes('additional subject') || req.subject.toLowerCase().includes('other subject')) continue;

            validSubjectCount++;
            let matchedMark = checkSubjectMatch(req.subject);

            let reqLevel = parseInt(req.level || '0', 10);
            if (isNaN(reqLevel) || req.level === "Unspecified") reqLevel = 0;

            let reqPercStr = req.percentage || '';
            let reqPerc = 0;
            if (reqPercStr) {
                if (reqPercStr.includes('-')) {
                    reqPerc = parseInt(reqPercStr.split('-')[0], 10);
                } else {
                    reqPerc = parseInt(reqPercStr.replace(/[^0-9]/g, ''), 10);
                }
            }
            if (isNaN(reqPerc)) reqPerc = 0;

            totalMinPerc += reqPerc;

            if (!matchedMark) {
                meetsSubjects = false;
                subjectFails.push(`Missing: ${req.subject}`);
                // Use 0 for user percentage, so totalUserPerc doesn't increase
                continue;
            }

            totalUserPerc += matchedMark.percentage;

            if (reqLevel > 0 && matchedMark.level < reqLevel) {
                meetsSubjects = false;
                subjectFails.push(`${req.subject} (Need L${reqLevel}, Got L${matchedMark.level})`);
            } else if (reqPerc > 0 && matchedMark.percentage < reqPerc) {
                meetsSubjects = false;
                subjectFails.push(`${req.subject} (Need ${reqPerc}%, Got ${matchedMark.percentage}%)`);
            }
        }
    }

    // Handle average percentages
    // If no valid subjects, avgUserPerc should not drag down rawScore
    let avgUserPerc = validSubjectCount > 0 ? (totalUserPerc / validSubjectCount) : (isFps ? userScore : 100);
    let avgMinPerc = validSubjectCount > 0 ? (totalMinPerc / validSubjectCount) : (isFps ? targetScore : 0);

    let meetsTargetScore = false;
    if (targetScore === 0) {
        meetsTargetScore = true;
    } else {
        meetsTargetScore = (userScore >= targetScore);
    }

    let meetsAllMinimums = meetsSubjects && meetsTargetScore;

    let rawScore = 0;
    let rawMin = 0;

    if (!isFps) { // Standard APS logic
        rawScore = ((userAps / MAX_APS) * 100) * 0.50 + (avgUserPerc) * 0.50;
        rawMin = ((reqAps / MAX_APS) * 100) * 0.50 + (avgMinPerc) * 0.50;
    } else { // FPS only
        rawScore = avgUserPerc;
        rawMin = avgMinPerc;
    }

    let mappedScore = 0;

    if (meetsAllMinimums) {
        if (rawMin >= 100) {
            mappedScore = 100;
        } else {
            mappedScore = 50 + ((rawScore - rawMin) / (100 - rawMin)) * 50;
        }
    } else {
        if (rawMin <= 0) {
            mappedScore = 0;
        } else {
            mappedScore = (rawScore / rawMin) * 49;
            // clamp it to 49 strictly if rawScore > rawMin but user still failed requirements (e.g. met APS, failed subjects)
            mappedScore = Math.min(mappedScore, 49);
        }
    }

    // Clamp score
    mappedScore = Math.max(0, Math.min(100, Math.round(mappedScore)));

    let reason = meetsAllMinimums
        ? `Met all requirements! Your score reflects how far above the minimum you are.`
        : `Failed requirements: ${subjectFails.join(', ')}` + (userScore < targetScore ? ` Your ${isFps ? 'FPS' : 'APS'} (${userScore}) is below required (${targetScore}).` : '');

    if (userScore < targetScore && subjectFails.length === 0) {
        reason = `Failed requirements: Your ${isFps ? 'FPS' : 'APS'} (${userScore}) is below required (${targetScore}).`;
    }

    console.log({ percent: mappedScore, reason: reason, rawScore, rawMin, avgUserPerc, avgMinPerc });
}
testLogic();
