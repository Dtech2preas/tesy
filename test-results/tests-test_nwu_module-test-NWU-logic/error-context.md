# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests/test_nwu_module.spec.js >> test NWU logic
- Location: tests/test_nwu_module.spec.js:3:1

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: page.waitForSelector: Test timeout of 30000ms exceeded.
Call log:
  - waiting for locator('.subject-row') to be visible

```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - generic [ref=e2]:
    - heading "North-West University (NWU)" [level=1] [ref=e3]
    - link "← Back Home" [ref=e4] [cursor=pointer]:
      - /url: index.html
  - generic [ref=e5]:
    - generic [ref=e6]: Find a Course
    - textbox "Find a Course" [ref=e7]:
      - /placeholder: Type to search courses...
    - generic [ref=e8]: Or Select from List
    - combobox "Or Select from List" [ref=e9]:
      - option "-- Loading Courses... --" [selected]
  - paragraph [ref=e11]: No subjects found. Please go back to the main page and enter your subjects first.
```

# Test source

```ts
  1  | const { test, expect } = require('@playwright/test');
  2  |
  3  | test('test NWU logic', async ({ page }) => {
  4  |     await page.goto('http://localhost:8000/nwu.html');
  5  |
  6  |     // Check subject rows
> 7  |     await page.waitForSelector('.subject-row');
     |                ^ Error: page.waitForSelector: Test timeout of 30000ms exceeded.
  8  |
  9  |     const selects = await page.$$('.subject-select');
  10 |     if (selects.length > 0) {
  11 |         await selects[0].selectOption({ label: 'Mathematics' });
  12 |         const marks = await page.$$('.subject-percentage');
  13 |         await marks[0].fill('65');
  14 |
  15 |         if (selects.length > 1) {
  16 |             await selects[1].selectOption({ label: 'Physical Sciences' });
  17 |             await marks[1].fill('75');
  18 |         }
  19 |         if (selects.length > 2) {
  20 |             await selects[2].selectOption({ label: 'English Home Language' });
  21 |             await marks[2].fill('85');
  22 |         }
  23 |     }
  24 |
  25 |     await page.click('#calculate-btn');
  26 |
  27 |     await page.waitForTimeout(2000);
  28 |
  29 |     const courses = await page.$$eval('.course-card h4', els => els.map(el => el.textContent));
  30 |     console.log(`Found ${courses.length} courses.`);
  31 | });
  32 |
```