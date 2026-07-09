import { UniversityModule } from '../../core/engine.js';
import { calculateStandardLikelihood } from '../../core/shared_calculator.js';
import { checkSubjectMatch } from '../../core/engine_utils.js';

export default class extends UniversityModule {
    constructor(uniId) {
        super(uniId);
    }

    calculateEligibility(course, userMarks, userAps, userFps) {
        let clonedCourse = JSON.parse(JSON.stringify(course));

        if (clonedCourse.required_subjects && Array.isArray(clonedCourse.required_subjects)) {
            let processedReqs = [];
            for (let req of clonedCourse.required_subjects) {
                if (req.subject && typeof req.subject === 'string' && req.subject.includes(' or ')) {
                    let parts = req.subject.split(/ or /i);
                    if (parts.length > 1 && req.subject.includes(':')) {
                         // This is a grouped "OR" requirement with specific levels (e.g., Maths: Level 3 or Tech Maths: Level 5)
                         // We need to evaluate them here and push ONLY the best matching one so the main calculator
                         // treats it as a single satisfied requirement, rather than separate AND requirements.

                         let bestMatchPart = null;
                         let bestMatchScore = -1;
                         let fallbackReq = null; // Use the first part if no match is found so it can fail gracefully

                         for (let part of parts) {
                             part = part.trim();
                             let subjectName = part;
                             let subjectLevel = req.level || "";

                             let levelMatch = part.match(/(.*?):\s*(?:Level|Code)?\s*(\d+)/i);
                             if (levelMatch) {
                                 subjectName = levelMatch[1].trim();
                                 subjectLevel = levelMatch[2].trim();
                             }

                             if (!fallbackReq) {
                                 fallbackReq = { subject: subjectName, level: subjectLevel, percentage: req.percentage || "" };
                             }

                             let userMark = checkSubjectMatch(subjectName, userMarks, this.helperData);

                             if (userMark) {
                                // If the user has this subject, we score it based on the mark.
                                if (userMark.percentage > bestMatchScore) {
                                    bestMatchScore = userMark.percentage;
                                    bestMatchPart = {
                                        subject: subjectName,
                                        level: subjectLevel,
                                        percentage: req.percentage || ""
                                    };
                                }
                             }
                         }

                         if (bestMatchPart) {
                             processedReqs.push(bestMatchPart);
                         } else {
                             // Push the original string back so the engine can fail it with the full reason
                             processedReqs.push(req);
                         }
                    } else {
                        processedReqs.push(req);
                    }
                } else {
                    processedReqs.push(req);
                }
            }
            clonedCourse.required_subjects = processedReqs;
        }

        return calculateStandardLikelihood(clonedCourse, userMarks, userAps, userFps, this.helperData);
    }
}
