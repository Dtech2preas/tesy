// Real logic template to be used inside generate_uni_pages.py

function checkSubjectMatch(reqSubjectName, userMarks, helperData) {
    if (!reqSubjectName) return null;
    let reqLower = reqSubjectName.toLowerCase().trim();

    // Special exact case to prevent bleed:
    let matchedMainSubject = null;

    if (helperData) {
        for (const mainSub in helperData) {
            let altFound = false;
            for (const altName of helperData[mainSub]) {
                let altLower = altName.toLowerCase().trim();
                if (reqLower === altLower) {
                    matchedMainSubject = mainSub;
                    altFound = true;
                    break;
                }
            }
            if (altFound) break;
        }

        if (!matchedMainSubject) {
            for (const mainSub in helperData) {
                let altFound = false;
                for (const altName of helperData[mainSub]) {
                    let altLower = altName.toLowerCase().trim();
                    if (reqLower.includes(altLower) || altLower.includes(reqLower)) {
                        if (reqLower.includes("literacy") && !altLower.includes("literacy")) continue;
                        if (altLower.includes("literacy") && !reqLower.includes("literacy")) continue;
                        if (reqLower.includes("technical") && !altLower.includes("technical")) continue;
                        if (altLower.includes("technical") && !reqLower.includes("technical")) continue;

                        matchedMainSubject = mainSub;
                        altFound = true;
                        break;
                    }
                }
                if (altFound) break;
            }
        }
    }

    if (!matchedMainSubject) {
        matchedMainSubject = reqSubjectName;
    }

    let bestMark = null;

    for (let mark of userMarks) {
        let markLower = mark.subject.toLowerCase().trim();
        let markMainSubject = null;

        if (helperData) {
            for (const mainSub in helperData) {
                let altFound = false;
                for (const altName of helperData[mainSub]) {
                    if (markLower === altName.toLowerCase().trim()) {
                        markMainSubject = mainSub;
                        altFound = true;
                        break;
                    }
                }
                if (altFound) break;
            }
        }

        if (!markMainSubject) {
            markMainSubject = mark.subject;
        }

        if (markMainSubject === matchedMainSubject) {
            if (!bestMark || mark.percentage > bestMark.percentage) {
                bestMark = mark;
            }
        }
    }

    if (bestMark) return bestMark;

    for (let mark of userMarks) {
        let markLower = mark.subject.toLowerCase().trim();
        if (reqLower === markLower) return mark;

        if (reqLower.includes(markLower) || markLower.includes(reqLower)) {
            if (reqLower.includes("literacy") && !markLower.includes("literacy")) continue;
            if (markLower.includes("literacy") && !reqLower.includes("literacy")) continue;
            if (reqLower.includes("technical") && !markLower.includes("technical")) continue;
            if (markLower.includes("technical") && !reqLower.includes("technical")) continue;
            return mark;
        }
    }

    return null;
}

function calculateLikelihood(course, userMarks, userAps, userFps, helperData) {
    let MAX_APS = 42;
    let effectiveUserAps = Math.min(userAps, MAX_APS);

    let reqAps = parseInt(course.aps || '0', 10);
    let reqFps = parseInt(course.fps || '0', 10);

    if (course.aps_range) {
        let parts = course.aps_range.split('-');
        if (parts.length > 0) reqAps = parseInt(parts[0], 10);
    }

    let isFps = (reqFps > 0 && reqAps === 0);
    let targetScore = isFps ? reqFps : reqAps;
    let userScore = isFps ? userFps : effectiveUserAps;

    let meetsSubjects = true;
    let subjectFails = [];

    let totalUserPerc = 0;
    let totalMinPerc = 0;
    let validSubjectCount = 0;

    // "OR" matching logic
    let groupedReqs = [];
    if (course.required_subjects && course.required_subjects.length > 0) {
        let currentGroup = [];
        for (let i = 0; i < course.required_subjects.length; i++) {
            let req = course.required_subjects[i];
            if (!req.subject || req.subject.toLowerCase().includes('additional subject') || req.subject.toLowerCase().includes('other subject')) continue;

            let sLower = req.subject.toLowerCase().trim();
            if (sLower.startsWith('or ') || sLower.includes(' or ')) {
                if (sLower.startsWith('or ')) {
                    req.subject = req.subject.substring(3).trim();
                }
                if (currentGroup.length === 0 && groupedReqs.length > 0) {
                    groupedReqs[groupedReqs.length - 1].push(req);
                } else {
                    currentGroup.push(req);
                }
            } else {
                if (currentGroup.length > 0) {
                    groupedReqs.push(currentGroup);
                }
                currentGroup = [req];
            }
        }
        if (currentGroup.length > 0) {
            groupedReqs.push(currentGroup);
        }
    }

    // Merge implicitly grouped alternative subjects (e.g., Mathematics and Mathematical Literacy in sequence)
    let mergedGroups = [];
    for (let grp of groupedReqs) {
        if (mergedGroups.length > 0) {
            let lastGrp = mergedGroups[mergedGroups.length - 1];
            let isMath1 = grp[0].subject.toLowerCase().includes('math');
            let isMath2 = lastGrp[0].subject.toLowerCase().includes('math');
            let isEng1 = grp[0].subject.toLowerCase().includes('english');
            let isEng2 = lastGrp[0].subject.toLowerCase().includes('english');

            if ((isMath1 && isMath2) || (isEng1 && isEng2)) {
                lastGrp.push(...grp);
            } else {
                mergedGroups.push(grp);
            }
        } else {
            mergedGroups.push(grp);
        }
    }

    for (let group of mergedGroups) {
        validSubjectCount++;

        let bestMatch = null;
        let groupFails = [];
        let groupMet = false;

        for (let req of group) {
            let matchedMark = checkSubjectMatch(req.subject, userMarks, helperData);
            let reqLevel = parseInt(req.level || '0', 10);
            if (isNaN(reqLevel) || req.level === "Unspecified") reqLevel = 0;

            let reqPercStr = req.percentage || '';
            let reqPerc = 0;
            if (reqPercStr) {
                if (reqPercStr.includes('-')) reqPerc = parseInt(reqPercStr.split('-')[0], 10);
                else reqPerc = parseInt(reqPercStr.replace(/[^0-9]/g, ''), 10);
            }
            if (isNaN(reqPerc)) reqPerc = 0;

            if (!matchedMark) {
                groupFails.push(`Missing: ${req.subject}`);
                continue;
            }

            let subMet = true;
            if (reqLevel > 0 && matchedMark.level < reqLevel) {
                subMet = false;
                groupFails.push(`${req.subject} (Need L${reqLevel}, Got L${matchedMark.level})`);
            } else if (reqPerc > 0 && matchedMark.percentage < reqPerc) {
                subMet = false;
                groupFails.push(`${req.subject} (Need ${reqPerc}%, Got ${matchedMark.percentage}%)`);
            }

            if (subMet) {
                bestMatch = { req: req, mark: matchedMark, reqPerc: reqPerc };
                groupMet = true;
                break;
            } else if (!bestMatch || (bestMatch && !bestMatch.mark)) {
                bestMatch = { req: req, mark: matchedMark, reqPerc: reqPerc };
            }
        }

        if (groupMet) {
            totalMinPerc += bestMatch.reqPerc;
            totalUserPerc += bestMatch.mark.percentage;
        } else {
            meetsSubjects = false;
            if (bestMatch && bestMatch.mark) {
                totalMinPerc += bestMatch.reqPerc;
                totalUserPerc += bestMatch.mark.percentage;
            } else {
                let avgReqPerc = 0;
                group.forEach(r => {
                    let rp = parseInt(r.percentage || '0', 10);
                    if(rp > avgReqPerc) avgReqPerc = rp;
                });
                totalMinPerc += avgReqPerc;
            }
            subjectFails.push(groupFails.join(' OR '));
        }
    }

    let meetsTargetScore = false;
    if (targetScore === 0) {
        meetsTargetScore = true;
    } else {
        meetsTargetScore = (userScore >= targetScore);
    }

    let meetsAllMinimums = meetsSubjects && meetsTargetScore;

    let rawScore = 0;
    let rawMin = 0;

    if (validSubjectCount > 0) {
        let avgUserPerc = totalUserPerc / validSubjectCount;
        let avgMinPerc = totalMinPerc / validSubjectCount;
        if (!isFps) {
            // Standard APS logic, 50% APS weight, 50% subject average weight
            rawScore = ((effectiveUserAps / MAX_APS) * 100) * 0.50 + (avgUserPerc) * 0.50;
            rawMin = ((reqAps / MAX_APS) * 100) * 0.50 + (avgMinPerc) * 0.50;
        } else {
            rawScore = avgUserPerc;
            rawMin = avgMinPerc;
        }
    } else {
        // No required subjects -> 100% based on APS/FPS score
        if (!isFps) {
            rawScore = ((effectiveUserAps / MAX_APS) * 100);
            rawMin = ((reqAps / MAX_APS) * 100);
        } else {
            rawScore = userScore;
            rawMin = targetScore;
        }
    }

    let mappedScore = 0;

    if (meetsAllMinimums) {
        if (rawMin >= 100 && !isFps) {
            mappedScore = 100;
        } else if (isFps && rawMin >= 600) {
            mappedScore = 100;
        } else {
            let maxPossible = isFps ? 600 : 100;
            if (rawScore >= maxPossible) {
                mappedScore = 100;
            } else {
                mappedScore = 50 + ((rawScore - rawMin) / (maxPossible - rawMin)) * 50;
            }
        }
    } else {
        if (rawMin <= 0) {
            mappedScore = 0; // Edge case
        } else {
            mappedScore = (rawScore / rawMin) * 49;
            mappedScore = Math.min(mappedScore, 49);
        }
    }

    mappedScore = Math.max(0, Math.min(100, Math.round(mappedScore)));

    let reason = "";
    let scoreType = isFps ? "FPS" : "APS";

    if (meetsAllMinimums) {
        reason = `Met all requirements! Your score reflects how far above the minimums you are.`;
    } else {
        let parts = [];
        if (subjectFails.length > 0) parts.push(`Failed subjects: ${subjectFails.join(', ')}`);
        if (!meetsTargetScore) parts.push(`Your ${scoreType} (${userScore}) is below required (${targetScore})`);
        reason = parts.join('. ');
    }

    return { percent: mappedScore, reason: reason };
}
