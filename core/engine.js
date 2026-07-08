export class UniversityModule {
    constructor(uniId) {
        this.uniId = uniId;
        this.courses = [];
        this.helperData = {};
    }

    async init() {
        // Load default helper data
        let globalHelper = {};
        try {
            const res = await fetch('./core/helper.json');
            if (res.ok) {
                globalHelper = await res.json();
            }
        } catch (e) {
            console.warn("Could not load global helper.json", e);
        }

        // Load local helper data if exists
        let localHelper = {};
        try {
            const res = await fetch(`./universities/${this.uniId}/helper.json`);
            if (res.ok) {
                localHelper = await res.json();
            }
        } catch (e) {
            // Local helper is optional
        }

        this.helperData = { ...globalHelper, ...localHelper };

        // Load courses
        try {
            const res = await fetch(`./universities/${this.uniId}/data.json`);
            if (res.ok) {
                const data = await res.json();
                let allCourses = [];
                let faculties = Object.keys(data);
                faculties.forEach(faculty => {
                    let courseList = data[faculty];
                    if (Array.isArray(courseList)) {
                        courseList.forEach(course => {
                            course.facultyName = faculty;
                            allCourses.push(course);
                        });
                    }
                });
                allCourses.sort((a, b) => a.course_name.localeCompare(b.course_name));
                this.courses = allCourses;
            } else {
                console.error(`Failed to load data for ${this.uniId}`);
            }
        } catch (e) {
            console.error(`Failed to load data for ${this.uniId}`, e);
        }
    }

    getCourses() {
        return this.courses;
    }

    searchCourses(query) {
        if (!query) return this.courses;
        const q = query.toLowerCase();
        return this.courses.filter(c => c.course_name.toLowerCase().includes(q));
    }

    getCourse(courseId) {
        return this.courses[courseId];
    }

    calculateEligibility(course, userMarks, userAps, userFps) {
        throw new Error("calculateEligibility must be implemented by subclasses");
    }
}

export class UniversityLoader {
    static async load(uniId) {
        try {
            const module = await import(`../universities/${uniId}/module.js`);
            const uniEngine = new module.default(uniId);
            await uniEngine.init();
            return uniEngine;
        } catch (e) {
            console.error(`Failed to load university module for ${uniId}`, e);
            throw e;
        }
    }
}
