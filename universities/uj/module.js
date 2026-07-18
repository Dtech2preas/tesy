import { UniversityModule } from '../../core/engine.js';
import { calculateStandardLikelihood } from '../../core/shared_calculator.js';

export default class extends UniversityModule {
    constructor(uniId) {
        super(uniId);
    }

    calculateEligibility(course, userMarks, userAps, userFps) {
        // We rely on the scraper having already separated academic vs non-academic requirements.
        // We just pass the course directly to the standard calculator.
        return calculateStandardLikelihood(course, userMarks, userAps, userFps, this.helperData);
    }
}
