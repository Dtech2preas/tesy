## 2024-05-18 - Dynamic Form Label Associations
**Learning:** When injecting form elements dynamically via innerHTML (e.g., adding subject rows), static labels fail screen reader accessibility. Generating a unique ID counter (`globalRowId`) ensures each input gets a distinct `id` and its corresponding `label` correctly targets it with the `for` attribute.
**Action:** Always generate and use unique IDs for dynamically created inputs to ensure their labels properly associate for assistive technology.
