## 2024-05-18 - Promise.all Optimization in University Recommendations
**Learning:** Sequential `await` in loops (`for...of`) causes a significant performance bottleneck when loading module definitions or JSON configuration files for many individual modules. Converting to `Promise.all` effectively concurrentizes I/O and evaluation across items.
**Action:** Always prefer `Promise.all` when mapping over collections where the output of one iteration is not dependent on the result of the previous one.
