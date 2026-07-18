import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import UJModule from './module.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const dataPath = path.join(__dirname, 'data.json');
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));

const moduleInstance = new UJModule('uj');
// manually set helper data if needed, or rely on empty
moduleInstance.helperData = {
    "Mathematics": ["Mathematics", "Maths"],
    "Mathematical Literacy": ["Mathematical Literacy", "Maths Lit"],
    "Technical Mathematics": ["Technical Mathematics", "Tech Maths"],
    "English": ["English Home Language", "English First Additional Language", "English", "Additional Language"],
    "Physical Science": ["Physical Sciences", "Physical Science", "Physics"],
    "Technical Science": ["Technical Science", "Tech Science"],
    "Life Science": ["Life Sciences", "Life Science", "Biology"],
    "Additional Subject(s)": ["Additional Subject", "Other Subject"]
};

let allCourses = [];
for (let faculty in data) {
    data[faculty].forEach(course => {
        allCourses.push(course);
    });
}

const profiles = [
    {
        name: "Distinction Student",
        aps: 42,
        fps: 420,
        marks: [
            { subject: "English", percentage: 90 },
            { subject: "Mathematics", percentage: 90 },
            { subject: "Physical Science", percentage: 90 },
            { subject: "Life Science", percentage: 90 },
            { subject: "Geography", percentage: 90 },
            { subject: "Accounting", percentage: 90 },
            { subject: "Technical Science", percentage: 90 },
            { subject: "Technical Mathematics", percentage: 90 }
        ]
    },
    {
        name: "Average Student",
        aps: 28,
        fps: 280,
        marks: [
            { subject: "English", percentage: 60 },
            { subject: "Mathematical Literacy", percentage: 60 },
            { subject: "Life Science", percentage: 60 },
            { subject: "Business Studies", percentage: 60 },
            { subject: "History", percentage: 60 },
            { subject: "Tourism", percentage: 60 }
        ]
    },
    {
        name: "Low Student",
        aps: 20,
        fps: 200,
        marks: [
            { subject: "English", percentage: 40 },
            { subject: "Mathematical Literacy", percentage: 40 },
            { subject: "History", percentage: 40 },
            { subject: "Tourism", percentage: 40 },
            { subject: "Life Orientation", percentage: 40 },
            { subject: "Geography", percentage: 40 }
        ]
    }
];

let genuineZeroCount = 0;
let potentialParserErrorCount = 0;
let resultsOutput = "";

allCourses.forEach(course => {
    profiles.forEach(profile => {
        try {
            let result = moduleInstance.calculateEligibility(course, profile.marks, profile.aps, profile.fps);
            if (result.likelihood === 0) {
                let isGenuine = true;
                if (profile.name === "Distinction Student") {
                    let reqNames = result.reason.split("Missing or significantly below required subject(s): ")[1] || "";
                    if (!reqNames.includes("IsiZulu") && !reqNames.includes("Afrikaans") && !reqNames.includes("Sepedi") && !reqNames.includes("Additional Language")) {
                         isGenuine = false;
                    }
                }

                if (isGenuine) {
                    genuineZeroCount++;
                } else {
                    potentialParserErrorCount++;
                    resultsOutput += `\n[PARSER ISSUE?] 0% Likelihood for ${course.course_name} with profile ${profile.name}\n`;
                    resultsOutput += `Reason: ${result.reason}\n`;
                    resultsOutput += `Required Subjects: ${JSON.stringify(course.required_subjects)}\n`;
                    resultsOutput += `Raw Requirements: ${course.rawRequirements}\n`;
                }
            }
        } catch (e) {
            potentialParserErrorCount++;
            resultsOutput += `\nERROR evaluating ${course.course_name} with profile ${profile.name}: ${e.message}\n`;
        }
    });
});

console.log(`Total Courses: ${allCourses.length}`);
console.log(`Genuine 0% Results (Expected due to low marks/missing subjects): ${genuineZeroCount}`);
console.log(`Potential Parser Errors (0% on Distinction Student for common subjects): ${potentialParserErrorCount}`);

if (potentialParserErrorCount > 0) {
    fs.writeFileSync(path.join(__dirname, 'test_failures.txt'), resultsOutput);
    console.log("Check test_failures.txt for details on potential parser errors.");
} else {
    fs.writeFileSync(path.join(__dirname, 'test_failures.txt'), "No parser errors detected.");
    console.log("No potential parser issues detected!");
}
