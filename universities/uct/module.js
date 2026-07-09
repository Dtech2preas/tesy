import { UniversityModule } from '../../core/engine.js';
import { calculateStandardLikelihood } from '../../core/shared_calculator.js';

export default class extends UniversityModule {
    constructor(uniId) {
        super(uniId);
    }

    calculateEligibility(course, userMarks, userAps, userFps) {
        // Since UCT's FPS is calculated as the sum of 6 subjects excluding Life Orientation,
        // we can override userFps if it's not correctly set, or just calculate it locally.
        let calculatedFps = 0;
        let subjects = userMarks.filter(m => m.subject.toLowerCase() !== 'life orientation' && m.subject.toLowerCase() !== 'lo');

        // Sort subjects by highest marks
        subjects.sort((a, b) => b.percentage - a.percentage);

        // Sum top 6 subjects
        for (let i = 0; i < Math.min(6, subjects.length); i++) {
            calculatedFps += subjects[i].percentage;
        }

        // Use the higher of provided userFps or calculatedFps
        let finalFps = Math.max(userFps || 0, calculatedFps);

        // If a specific band has been selected and injected into the course object via UI
        if (course.selectedBand) {
            // Clone the course to avoid modifying the original globally
            let tempCourse = { ...course };

            // Override properties with the selected band's properties
            tempCourse.required_subjects = course.selectedBand.required_subjects;

            // For UCT, we mainly compare against FPS or WPS.
            tempCourse.fps = course.selectedBand.score;
            tempCourse.aps = ""; // Clear standard APS so it relies on FPS

            return calculateStandardLikelihood(tempCourse, userMarks, userAps, finalFps, this.helperData);
        }

        // Default behavior if no band is provided
        return calculateStandardLikelihood(course, userMarks, userAps, finalFps, this.helperData);
    }
}
