# 原图气泡标注 surface brief

Mode: Operate. Existing surface extension, code-led; preserve the incumbent light engineering review workbench. This brief applies only to original compression-spring drawing annotations in `frontend/app.js`, `frontend/drawing-annotations.js`, and their scoped CSS.

THESIS: Give engineers reliable navigation between original drawing evidence and the existing parameter editor, without creating another editable parameter source.

OWN-WORLD: Inherit the current light engineering workbench, blue controls, Chinese system typography, and compact data rows. Numbered SVG circles and thin leaders are evidence navigation, not decorative illustration.

STORY: Upload and recognize, locate original evidence, check current values; unreliable locations remain explicitly unlocated and can be placed manually.

FIRST VIEWPORT: Page selection and annotation controls in the original-image toolbar; numbered balloons on the drawing and matching parameter-row buttons; concise status and collapsible unlocated details under the drawing.

FORM: A local Operate extension. No new visual identity, comp-led rebuild, or concept tournament. Current user-provided drawing is runtime content; browser fixtures are clearly labeled synthetic, not shipping illustration assets.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

Artifact-grounded handoff is recorded here and in `docs/drawing-annotations.md`. The independent follow-up disposition is `ship`, scoped to the annotation #2 navigation fix: the standard-number balloon now opens and focuses its parameter row, while existing standardization links retain their standards-pane behavior. No broader product verdict or external Qwen/SolidWorks execution is implied. This local extension does not create or replace root PRODUCT.md, DESIGN.md, or visual-system sidecars.

Constraints: Do not annotate generated SolidWorks images or change comparison-viewer behavior. Annotation writes use a separate revision, do not change engineering parameters, and must preserve local positions on save failure. Mobile controls wrap without overflow; balloons stay readable across zoom levels. Existing design-system documentation remains unchanged for this local feature.

Feature and persistence contract: `docs/drawing-annotations.md`.

## Recorded surface rules

The built surface inherits the white and light neutral workbench, blue controls, and the existing Segoe UI Variable / Microsoft YaHei UI / Microsoft YaHei / Arial font stack. Compact controls and status copy use 12px text; balloon numbers use 13px bold white text. This is observed feature styling, not a new global token system.

**Evidence navigation rule.** Blue SVG circles and thin leaders carry fixed parameter identifiers, not approval state. Each balloon keeps a 15px radius in viewport coordinates across image zoom; its anchor and bubble positions are normalized to the displayed page. Hover, keyboard focus, and selection use a darker blue fill with a gold outline. The parameter-row number has a visible keyboard focus ring. Original and current values are separately labeled below the drawing.

**One parameter editor rule.** Balloon activation opens the existing parameter view, scrolls to the row, highlights it, and focuses its value control. In adjustment mode pointer drag moves only the balloon; manual placement resets the anchor on the current page. Neither focus nor a location write confirms or edits a parameter.

**Recoverable location rule.** Save/loading states and conflict actions appear beside the original-image controls or in the information area. Pending positions remain in the current browser session after failure; the cache does not survive refresh. An original-document change prevents reuse of old local positions. Unlocated details remain collapsible, with an explicit manual-placement action.

Toolbar controls wrap with 8px gaps; toolbar and information-area buttons have a minimum 32px height. Parameter-row number buttons have a minimum 26px width and height. The information area is bounded to 160px and scrolls when needed; long values wrap. Desktop keeps drawing and data side by side, while the existing mobile layout stacks the drawing above the parameter view. Preserve these scoped patterns without promoting their task-specific measurements into project-wide rules.

Evidence: current `frontend/app.js`, `frontend/drawing-annotations.js`, scoped annotation CSS in `frontend/styles.css`, and desktop/mobile captures in `.impeccable/review/desktop.jpg` and `mobile.jpg`. Captures use a drawing labeled as demonstration/test data, are Git-ignored QA artifacts, and are not shipping imagery. User uploads and page previews remain runtime content; this feature ships no new raster assets. Implementation and regression details are in `docs/drawing-annotations.md`.

Not canonized: synthetic drawing content, screenshot composition, and annotation-only dimensions are not a visual identity or reusable global design system.

## Original annotation locator v2 — 2026-10-14

Disposition: ship for the existing 15-field evidence-navigation surface. Coordinate normalization now uses displayed EXIF orientation and polygon/center semantics; ambiguous locations remain explicit. New local OCR results are cached and never modify engineering values. Existing automatic locations upgrade once, while manual and unknown-origin locations remain protected under the independent annotation revision.

The SVG overlay keeps 15px circles and 13px numerals. A deterministic bounded pixel-space solver avoids other circles and OCR text before minimizing leader crossings and distance. Pan preserves layout; zoom/resize recompute automatic positions. Manual placement stays fixed and crowded views show a zoom/adjust hint without hiding labels.

Evidence: `scripts/test_drawing_annotations_v2.py`, API regression in SQLite/JSON modes (including a manual edit during rebuild and failure retention), UI collision/serial-save regression, and real browser pointer/zoom/pan/focus/save-reopen checks. Desktop 1440px and narrow 430px captures of both supplied local drawings are in ignored `outputs/annotation-qa/`; captures include a deliberate persisted manual-position test. Existing dimensions, confirmation/save-race and 64 shared SW export cases passed. Local API/worker rebuilt; API and web health returned 200, and both existing database orders upgraded without changing business data or review revisions. No cloud recognition or external SW job was submitted.

Mechanical detector ran once. Its HTML parser dependencies were unavailable, so its regex fallback was treated as incomplete; nine CSS accent-stripe warnings belong to unchanged risk/version surfaces outside this scoped edit. Changed overlay behavior was reviewed from rendered desktop/narrow captures and browser geometry assertions, rather than claiming a clean automated contrast audit. No new shipping raster assets or root visual-system replacement.


## Original annotation locator v3 — 2026-10-14

Disposition: ship for the existing evidence-navigation surface. The compact incumbent toolbar now includes a bounded local-OCR retry; controls disable during the operation, failed saves retain positions, revision conflicts stay explicit, and responses for another order never redraw the current order. Amber text below the image shows a source/current-value mismatch or diameter-role conflict without changing the engineering parameter. Existing typography, blue circles, independent revisions and manual-position protection remain in place.

Evidence: five supplied local drawings replayed through deterministic OCR parsing/fusion, with anchor-in-region assertions and preserved business snapshots. Browser tests cover all five at 1440px and 430px, retry failure/success, real pointer drag, focus, zoom/pan and save/reopen. Rendered captures in ignored `outputs/annotation-v3-qa/` were inspected for desktop and narrow layout; narrow crowding keeps every marker and displays the existing zoom/adjust hint. API tests cover SQLite/JSON, latest sidecar positions, stale revisions, ownership and concurrent edits; 61 design-value and 64 shared Python/JS SW cases passed. No new shipping raster assets, external recognition or real SW submission. The existing degraded detector result remains recorded above; no claim of a new clean mechanical audit.

The local API/worker were rebuilt and five persisted orders upgraded with exact business-snapshot/review-revision comparisons. The deployed OCR runtime uses a different model version, so native output coordinates and overlapping boxes were also checked. Original/current evidence metadata remains consistent after retry; the saved erroneous parameter is intentionally preserved for human correction. Both local health endpoints returned 200. A fresh in-app browser loaded the v3 script; authenticated ERP order viewing requires the user's existing ERP session, while browser interaction QA uses mocked APIs and real local images.
