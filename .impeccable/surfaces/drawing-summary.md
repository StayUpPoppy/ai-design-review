# 图纸摘要名称编辑

Mode: Operate. Scoped refinement of `frontend/app.js` `renderSummaryHtml` and the existing metric input styles in `frontend/styles.css`; preserve the light engineering workbench.

Keep the existing two-column desktop summary and stacked narrow layout. Replace the read-only drawing label with a native text input beside the existing drawing-number editor. Retain all unrelated metrics, history status colors and controls. No new modal or confirmation step. Length errors stay below the input; failed saves expose the existing retry treatment. Background diagnostics preserve the focused input node.

Disposition: ship. Desktop 1440×1000 and narrow 390×844 mocked-browser captures were inspected in ignored `outputs/decimal-coils-drawing-name-qa/`. Name and drawing-number fields are legible, aligned and contained. Native editing, focus, length errors, retry, conflicts and reopening were verified; decimal coil single/bulk confirmation and exact SW numeric output also passed. No visual assets or new color system.

The mechanical detector ran once with degraded HTML-parser coverage. Its reported accent stripes and sidebar layout transitions are unchanged surfaces outside this edit; no claim of a clean computed-contrast audit. Browser screenshots and overflow assertions cover the edited summary.
