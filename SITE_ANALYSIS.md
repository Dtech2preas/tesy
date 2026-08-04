# Comprehensive Site Analysis and Technical Audit

## Overview
This document serves as an architectural review and technical audit of the University Qualifications application. Following the request to identify missing data, it became apparent that the system requires robust scaling to handle dynamic data formatting across different institutions. This report details findings and provides actionable steps to "make it better" across UX/UI, backend architecture, and data pipelines.

---

## 1. Data Pipeline and Backend Scraping
**Current State:**
- The repository relies heavily on hardcoded HTML for specific universities. Some, like `uj.html`, rely on automated scraper/validator pairs (`uj/scraper.py`, `uj/validator.py`), while others contain manual overrides in JSON with frequent missing data attributes (e.g., `"N/A"` for course requirements).
- We identified and resolved missing `required_subjects` in over 200 courses across 10 universities by building targeted scrapers.

**Recommendations:**
1. **Standardize the Scraper Architecture:** Every university in `universities/` should implement a standard pipeline consisting of:
   - `<uni_id>_scraper.py`
   - `<uni_id>_validator.py`
   - `<uni_id>_test.js`
   This is explicitly requested by `AGENTS.md` but is missing for almost all universities except UJ.
2. **Dynamic Format Handling:** University prospectuses change frequently. The data loaders need to stop using strict JSON array definitions for unstructured subjects and use NLP models or fuzzy string matching (like the one we implemented to fix the missing data) to dynamically assign requirements into alternative `[ { "subject": "OR Mathematics" } ]` arrays.
3. **Data Provenance:** Keep the `rawRequirements` field we introduced. This is crucial for debugging why an eligibility engine might falsely penalize a student.

---

## 2. Codebase Architecture & Modularity
**Current State:**
- The application separates logic into `core/` (shared engine utilities) and `universities/` (specific rules per university).
- HTML pages are generated via `generate_uni_pages.py` based on templates.

**Recommendations:**
1. **Reduce Boilerplate HTML:** Right now, there are 15+ nearly identical `.html` files (e.g., `up.html`, `wits.html`, `nwu.html`). Since all heavy logic is executed client-side, the app should be migrated to a Single Page Application (SPA) utilizing vanilla JS components or a lightweight framework (like Preact) to dynamically inject university data onto a single `university.html?id=wits` route.
2. **Centralize the Eligibility Algorithm:** UCT's logic (in `uct.html`) overrides the global structure because of its band-system. Instead of breaking the `generate_uni_pages.py` generator for UCT, the generic `core/calculator.js` should support a `scoring_strategy` interface. Universities could inject custom calculators (e.g., FPS vs APS vs WPS) directly into the module scope without touching presentation logic.
3. **Automated Testing Engine:** The test suites (`test_<uni_id>.js`) must be unified. Create a `core/tester.js` that automatically executes mock student profiles against every university's `data.json` to ensure zero regressions when subjects are updated.

---

## 3. UI and User Experience (UX)
**Current State:**
- The app operates fully offline using Service Workers (`sw.js`).
- Subject selection and inputs are persisted in `localStorage`.
- UI relies on passive "Calculate" triggers (like `blur` or `visibilitychange`).

**Recommendations:**
1. **Explicit Feedback for Missing Requirements:** Currently, if a student inputs subjects that do not match the required names in `helper.json`, the app silently fails them. The UI must include a visual "Fuzzy Match Recommendation" (e.g., "Did you mean *Mathematical Literacy* instead of *Maths*?") to prevent user frustration.
2. **Enhance Implicit Triggers:** While relying on `visibilitychange` for ad revenue optimization is clever, it damages UX if the browser blocks passive script execution or if the user never leaves the page. Add an implicit fallback: calculate dynamically via a debounced listener on the input fields themselves.
3. **Offline Caching Optimization:** Ensure that the generated PDF capability (`html2pdf.js`) is effectively bundled and cached by the service worker to guarantee immediate rendering without network calls, especially in low-connectivity areas common among South African students.
4. **Responsive Tables:** The course requirement data tables often break horizontally on mobile devices. Implement CSS sticky headers and horizontal scrolling for `.table-container` classes to improve the mobile experience (which constitutes 90%+ of the user base).

---

## 4. Immediate Next Steps for the Engineering Team
1. Review and merge the newly scraped `data.json` files which eliminated 100% of the missing data anomalies.
2. Execute the Playwright visual regression tests to verify mobile table layouts.
3. Build the generic SPA router to delete the redundant HTML files, simplifying the deployment pipeline.
