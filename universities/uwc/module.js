import { UniversityModule } from '../../core/engine.js';
import { calculateStandardLikelihood } from '../../core/shared_calculator.js';

export default class extends UniversityModule {
    constructor(uniId) {
        super(uniId);
    }

    calculateEligibility(course, userMarks, userAps, userFps) {
        let courseCopy = JSON.parse(JSON.stringify(course));

        if (courseCopy.required_subjects && Array.isArray(courseCopy.required_subjects)) {
            let newReqs = [];
            for (let req of courseCopy.required_subjects) {
                let subjectStr = typeof req === 'object' ? req.subject : req;
                if (typeof subjectStr === 'string' && subjectStr.length > 30 && subjectStr.match(/Code \d/g) && subjectStr.match(/Code \d/g).length >= 2) {

                    let modified = subjectStr.replace(/\s+(English|Another language|Maths|Life Sciences|Physical Sciences|Accounting|Business Studies|Economics|History|Geography|Consumer Studies|Tourism|Information Technology|Engineering Graphics and Design|Agricultural Sciences)\b/gi, (match, p1, offset, string) => {
                        let prevStr = string.substring(Math.max(0, offset - 4), offset);
                        if (prevStr.toUpperCase().includes("OR")) {
                            return match;
                        } else {
                            return " |SPLIT| " + p1;
                        }
                    });

                    let parts = modified.split(" |SPLIT| ");

                    for (let p of parts) {
                        if (!p.trim()) continue;
                        let cleanP = p.replace(/\(home OR first additional language\)/ig, "");
                        let subParts = cleanP.split(/\s+or\s+|\s+OR\s+/);
                        if (subParts.length > 1) {
                            newReqs.push(subParts.map(sp => ({ subject: sp.trim() })));
                        } else {
                            // Wrap it in an array to forcefully separate it from the previous and next group!
                            newReqs.push([{ subject: cleanP.trim() }]);
                        }
                    }
                } else {
                    newReqs.push(req);
                }
            }
            courseCopy.required_subjects = newReqs;
        }

        return calculateStandardLikelihood(courseCopy, userMarks, userAps, userFps, this.helperData);
    }
}
