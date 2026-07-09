import { UniversityModule } from '../../core/engine.js';
import { calculateStandardLikelihood } from '../../core/shared_calculator.js';

export default class extends UniversityModule {
    constructor(uniId) {
        super(uniId);
    }

    calculateEligibility(course, userMarks, userAps, userFps) {
        // Based on my findings, UFS adds 1 bonus point to APS if Life Orientation is >= 60% (Level 5)
        let adjustedAps = userAps;
        let loMark = userMarks.find(m => m.subject.toLowerCase() === 'life orientation' || m.subject.toLowerCase() === 'lo');
        if (loMark && loMark.percentage >= 60) {
            adjustedAps += 1;
        }

        return calculateStandardLikelihood(course, userMarks, adjustedAps, userFps, this.helperData);
    }
}
