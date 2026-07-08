export function checkSubjectMatch(reqSubjectName, userMarks, helperData) {
    if (!reqSubjectName) return null;
    let reqLower = reqSubjectName.toLowerCase().trim();

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

export const isGarbage = (str) => {
    const s = typeof str === 'string' ? str.toLowerCase() : String(str).toLowerCase();
    const garbagePhrases = [
        'nsc/ieb', 'minimum requirements', 'will be prioritised', 'a diploma endorsement',
        'fighter i', 'hazmat', 'fire fighter', 'environment', 'enforcement department',
        'working experience', 'programme', 'hr division', 'bachelor', 'application',
        'write an essay', 'official letter', 'questionnaire', 'nqf level', 'combination of',
        'proof of employment'
    ];
    return garbagePhrases.some(phrase => s.includes(phrase));
};

export const isAdditionalSubject = (str) => {
    const s = typeof str === 'string' ? str.toLowerCase() : String(str).toLowerCase();
    return s.includes('additional subject') || s.includes('other subject') || s.includes('another subject') || s.includes('additional subjects') || s.includes('other subjects');
};

export const getAdditionalSubjectCount = (str) => {
    const s = typeof str === 'string' ? str.toLowerCase() : String(str).toLowerCase();
    if (s.includes('three') || s.includes('3')) return 3;
    if (s.includes('two') || s.includes('2')) return 2;
    return 1;
};

export const levelToMinPercent = (level) => {
    const map = { 1: 0, 2: 30, 3: 40, 4: 50, 5: 60, 6: 70, 7: 80 };
    return map[level] || 50;
};

export const getMinForRequirement = (req) => {
    if (typeof req === 'object' && req !== null) {
        if (req.minPercent !== undefined) return req.minPercent;
        if (req.minLevel !== undefined) return levelToMinPercent(req.minLevel);
        if (req.percentage !== undefined) {
            let percMatch = String(req.percentage).match(/(\d+)%/);
            if (percMatch) return parseInt(percMatch[1]);
            let num = parseInt(String(req.percentage).replace(/[^0-9]/g, ''), 10);
            if (!isNaN(num)) return num;
        }
        if (req.level !== undefined && req.level !== "Unspecified") {
            let lvl = parseInt(req.level);
            if (lvl > 7) return lvl;
            return levelToMinPercent(lvl);
        }
    }
    const levelMatch = String(req).match(/Level\s*(\d)/i);
    if (levelMatch) return levelToMinPercent(parseInt(levelMatch[1]));
    const percentMatch = String(req).match(/(\d+)%/);
    if (percentMatch) return parseInt(percentMatch[1]);
    return 50;
};

export function getLikelihoodClass(percent) {
    if (percent === 100) return 'likelihood-100';
    if (percent >= 70) return 'likelihood-high';
    if (percent >= 40) return 'likelihood-med';
    return 'likelihood-low';
}
