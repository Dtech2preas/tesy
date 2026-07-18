import { UniversityModule } from '../../core/engine.js';
import { calculateStandardLikelihood } from '../../core/shared_calculator.js';

export default class extends UniversityModule {
    constructor(uniId) {
        super(uniId);
    }

    calculateEligibility(course, userMarks, userAps, userFps) {
        let cleanedSubjects = [];

        for (let req of course.required_subjects || []) {
            let s = req.subject.toLowerCase();

            // Ignore instructional texts that were parsed into subject strings
            if (s.includes("and comply with") || s.includes("combination") ||
                s.includes("interview") || s.includes("portfolio") ||
                s.includes("audition") || s.includes("selection considers") ||
                s.includes("economic status") || s.includes("motivational letter") ||
                s.includes("a limited number of applicants")) {
                continue;
            }

            // Handle conditional subjects safely: "Mathematics (If you take Economics)"
            if (s.includes("(if you take") || s.includes("(if you choose") || s.includes("(if you wish")) {
                continue;
            }

            cleanedSubjects.push(req);
        }

        const cleanCourse = { ...course, required_subjects: cleanedSubjects };
        return calculateStandardLikelihood(cleanCourse, userMarks, userAps, userFps, this.helperData);
    }
}
