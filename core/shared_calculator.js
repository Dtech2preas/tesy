import { checkSubjectMatch, isGarbage, isAdditionalSubject, getAdditionalSubjectCount, levelToMinPercent, getMinForRequirement } from './engine_utils.js';

export function calculateStandardLikelihood(course, userMarks, userAps, userFps, helperData) {
    let hardFailReason = null;
    let usedSubjects = new Set();
    let additionalRequirements = [];
    let breakdown = [];

    if (course.required_subjects && Array.isArray(course.required_subjects)) {
        let groupedReqs = [];
        let currentGroup = [];
        for (let i = 0; i < course.required_subjects.length; i++) {
            let req = course.required_subjects[i];
            if (!req.subject || isGarbage(req.subject)) continue;

            if (isAdditionalSubject(req.subject)) {
                additionalRequirements.push(req);
                continue;
            }

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
            let passedOr = false;
            let bestMatchedSubject = null;
            let bestMatchedMark = null;

            for (let subj of group) {
                const subjectName = typeof subj === 'object' ? subj.subject || subj : subj;

                const minPct = getMinForRequirement(subj);

                for (let mark of userMarks) {
                    if (usedSubjects.has(mark.subject)) continue;

                    const matchedMark = checkSubjectMatch(subjectName, [mark], helperData);
                    if (matchedMark !== null) {
                        if (minPct === 0 || matchedMark.percentage >= minPct - 15) {
                            if (!bestMatchedMark || matchedMark.percentage > bestMatchedMark.percentage) {
                                bestMatchedMark = matchedMark;
                            }
                        }
                    }
                }
            }

            if (bestMatchedMark) {
                passedOr = true;
                usedSubjects.add(bestMatchedMark.subject);
                breakdown.push({
                    requirement: group.map(s => typeof s === 'object' ? (s.subject || s) : s).join(' OR '),
                    requiredMark: group.map(s => getMinForRequirement(s) + '%').join(' OR '),
                    userSubject: bestMatchedMark.subject,
                    userMark: bestMatchedMark.percentage + '%',
                    status: "Pass"
                });
            }

            if (!passedOr) {
                const subjNames = group.map(s => typeof s === 'object' ? (s.subject || s) : s).join(' OR ');
                const minPcts = group.map(s => getMinForRequirement(s) + '%').join(' OR ');
                breakdown.push({
                    requirement: subjNames,
                    requiredMark: minPcts,
                    userSubject: "None/Too Low",
                    userMark: "-",
                    status: "Fail"
                });
                hardFailReason = `Missing or significantly below required subject(s): ${subjNames}`;
                return { likelihood: 0, status: "ineligible", reason: hardFailReason, breakdown: breakdown };
            }
        }
        course._mergedGroups = mergedGroups;

        course._additionalRequirementsCalculated = [];
        for (let req of additionalRequirements) {
            let neededCount = getAdditionalSubjectCount(req.subject);
            let minPct = getMinForRequirement(req);

            for (let j = 0; j < neededCount; j++) {
                let bestUnusedMark = null;
                for (let mark of userMarks) {
                    if (usedSubjects.has(mark.subject) || mark.subject.toLowerCase() === 'life orientation' || mark.subject.toLowerCase() === 'lo') continue;

                    if (minPct === 0 || mark.percentage >= minPct - 15) {
                        if (!bestUnusedMark || mark.percentage > bestUnusedMark.percentage) {
                            bestUnusedMark = mark;
                        }
                    }
                }

                if (bestUnusedMark) {
                    usedSubjects.add(bestUnusedMark.subject);
                    course._additionalRequirementsCalculated.push({ req: req, mark: bestUnusedMark });
                    breakdown.push({
                        requirement: typeof req === 'object' ? (req.subject || req) : req,
                        requiredMark: minPct + '%',
                        userSubject: bestUnusedMark.subject,
                        userMark: bestUnusedMark.percentage + '%',
                        status: "Pass"
                    });
                } else {
                    breakdown.push({
                        requirement: typeof req === 'object' ? (req.subject || req) : req,
                        requiredMark: minPct + '%',
                        userSubject: "None/Too Low",
                        userMark: "-",
                        status: "Fail"
                    });
                    hardFailReason = `Not enough additional subjects meeting the requirements for: ${req.subject}`;
                    return { likelihood: 0, status: "ineligible", reason: hardFailReason, breakdown: breakdown };
                }
            }
        }
    }

    let minScore = null;
    let userScore = null;
    let maxSpread = 12.0;
    let scoreName = "";

    if (course.aps !== undefined || course.aps_range !== undefined) {
        minScore = course.aps !== undefined ? parseInt(course.aps, 10) : parseInt(String(course.aps_range).split('-')[0], 10);
        if (isNaN(minScore) || minScore === 0) minScore = null;
    }

    if (minScore !== null) {
        userScore = Math.min(userAps, 42);
        maxSpread = 12.0;
        scoreName = "APS";
        breakdown.push({
            requirement: "APS",
            requiredMark: minScore,
            userSubject: "Total APS",
            userMark: userScore,
            status: userScore >= minScore ? "Pass" : "Fail"
        });
    } else if (course.fps !== undefined) {
        minScore = parseInt(course.fps, 10);
        if (!isNaN(minScore) && minScore > 0) {
            userScore = userFps;
            maxSpread = 120.0;
            scoreName = "FPS";
            breakdown.push({
                requirement: "FPS",
                requiredMark: minScore,
                userSubject: "Total FPS",
                userMark: userScore,
                status: userScore >= minScore ? "Pass" : "Fail"
            });
        } else {
            minScore = null;
        }
    }

    let likelihood;
    let status = "eligible";
    let reason = `Strong match – ${scoreName} strength and subject performance`;

    if (minScore === null) {
        likelihood = 70;
        reason = "Meets all published requirements";
    } else {
        const relative = (userScore - minScore) / maxSpread;
        let strength = Math.max(0, Math.min(100, 55 + relative * 45));

        let avgSubjectScore = 100;
        let subjectScores = [];

        if (course._mergedGroups && course._mergedGroups.length > 0) {
            for (let group of course._mergedGroups) {
                let bestExcess = 0;
                let hasMinRequirement = false;

                for (let subj of group) {
                    const subjectName = typeof subj === 'object' ? subj.subject || subj : subj;
                    const matchedUserMark = checkSubjectMatch(subjectName, userMarks, helperData);

                    const minPct = getMinForRequirement(subj);
                    if (minPct > 0) hasMinRequirement = true;

                    if (matchedUserMark !== null && minPct > 0) {
                        const excess = ((matchedUserMark.percentage - minPct) / (100 - minPct)) * 100;
                        bestExcess = Math.max(bestExcess, Math.max(0, Math.min(100, excess)));
                    } else if (matchedUserMark !== null && minPct === 0) {
                        bestExcess = 100;
                    }
                }
                if (hasMinRequirement) {
                    subjectScores.push(bestExcess);
                } else {
                    subjectScores.push(100);
                }
            }
        }

        if (course._additionalRequirementsCalculated && course._additionalRequirementsCalculated.length > 0) {
            for (let addReq of course._additionalRequirementsCalculated) {
                const minPct = getMinForRequirement(addReq.req);
                if (minPct > 0) {
                    const excess = ((addReq.mark.percentage - minPct) / (100 - minPct)) * 100;
                    subjectScores.push(Math.max(0, Math.min(100, excess)));
                } else {
                    subjectScores.push(100);
                }
            }
        }

        if (subjectScores.length > 0) {
            avgSubjectScore = subjectScores.reduce((a, b) => a + b, 0) / subjectScores.length;
        }

        likelihood = Math.round(0.6 * avgSubjectScore + 0.4 * strength);
        likelihood = Math.max(10, Math.min(100, likelihood));

        if (userScore < minScore) {
            const diff = minScore - userScore;
            reason = `Slightly below minimum ${scoreName} (by ${diff} points) – low but possible chance`;
        } else {
            if (likelihood < 35) {
                reason = "Meets minimum but borderline – low but possible chance";
            } else if (likelihood < 50) {
                reason = "Meets minimum – decent chance";
            } else if (likelihood < 70) {
                reason = "Good match – solid chance";
            } else {
                reason = "Strong match – very competitive chance";
            }
        }
    }

    return { likelihood: Math.round(likelihood), status, reason, breakdown: breakdown };
}
