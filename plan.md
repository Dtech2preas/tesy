1. **Change the theme to a light, professional theme.** Update CSS variables in `core/styles.css`: `bg-color` to an off-white, `container-bg` to white, `text-color` to dark gray, and `primary-accent` to a standard professional blue (`#0056b3` or similar). Remove glowing shadows.
2. **Compact the layout for mobile.** Reduce padding on `card` elements, `subject-card`, and `uni-card`. Decrease the size of the APS/FPS gauges in the dashboard from `120px` to something smaller like `80px` or `90px` to save vertical space.
3. **Adjust inputs and floating labels.** Make inputs have a lighter background with a subtle border and darker text. Adjust `padding` and font sizes to make subject selection more compact.
4. **Update Index/HTML overrides if necessary.** Make sure icons and SVGs look correct in the light theme (e.g., setting their fill or stroke colors to match the new text/accent colors).
5. **Verify with Playwright.** Run the Playwright script to verify the visual changes and ensure everything looks professional and not "too big."
6. **Pre-commit checks.** Run pre-commit instructions.
7. **Submit.**
