import { UniversityModule } from '../../core/engine.js';
import { calculateStandardLikelihood } from '../../core/shared_calculator.js';

export default class extends UniversityModule {
    constructor(uniId) {
        super(uniId);
    }

    calculateEligibility(course, userMarks, userAps, userFps) {
        return calculateStandardLikelihood(course, userMarks, userAps, userFps, this.helperData);
    }
}
