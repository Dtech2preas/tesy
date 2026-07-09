import { UniversityModule } from '../../core/engine.js';
import { calculateStandardLikelihood } from '../../core/shared_calculator.js';

export default class extends UniversityModule {
    constructor(uniId) {
        super(uniId);
    }

    calculateEligibility(course, userMarks, userAps, userFps) {
        // Deep copy the course so we don't mutate the original data
        let courseCopy = JSON.parse(JSON.stringify(course));

        if (courseCopy.required_subjects) {
            let processedReqs = [];
            for (let req of courseCopy.required_subjects) {
                if (req.subject && req.subject.toLowerCase().includes(' or ')) {
                    let parts = req.subject.split(/ OR | or /i);
                    for (let part of parts) {
                        part = part.trim();
                        // Only match subject level patterns if they have a level like "Mathematics level 4"
                        let match = part.match(/(.*?)\s+(?:Code|Level\s*)?(\d+|null)/i);
                        if (match) {
                            processedReqs.push({ subject: 'OR ' + match[1].trim(), level: match[2] });
                        } else {
                            processedReqs.push({ subject: 'OR ' + part, level: req.level || "" });
                        }
                    }
                    // Fix the first one to not have 'OR ' so it starts a new group in shared_calculator
                    if (processedReqs.length > 0) {
                         let lastAdded = processedReqs.slice(-parts.length);
                         lastAdded[0].subject = lastAdded[0].subject.substring(3).trim();
                    }
                } else {
                    processedReqs.push(req);
                }
            }
            courseCopy.required_subjects = processedReqs;
        }

        return calculateStandardLikelihood(courseCopy, userMarks, userAps, userFps, this.helperData);
    }
}
