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
            const garbagePhrases = [
                "and comply with", "combination", "interview", "portfolio",
                "audition", "selection considers", "economic status", "motivational letter",
                "a limited number of applicants", "see additional requirements",
                "if you wish to take", "in the main instrument", "interfaculty programme",
                "students are selected", "base requirements:", "place for", "places in the programme",
                "information is available", "a national senior certificate", "you must have a diploma",
                "necessary qualifications", "extended curriculum programmes", "admission and selection",
                "applicants are also subject to selection", "selection mark", "limited spaces are available",
                "year mathematics and physics)", "applicants from the designated", "economic categories",
                "second bachelor's degree", "available as ecps", "extra year of study"
            ];

            if (garbagePhrases.some(phrase => s.includes(phrase))) {
                continue;
            }

            // Handle conditional subjects safely: "Mathematics (If you take Economics)"
            if (s.includes("(if you take") || s.includes("(if you choose")) {
                continue;
            }

            cleanedSubjects.push(req);
        }

        const cleanCourse = { ...course, required_subjects: cleanedSubjects };
        return calculateStandardLikelihood(cleanCourse, userMarks, userAps, userFps, this.helperData);
    }
}
