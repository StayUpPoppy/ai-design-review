# 审图原图90度旋转

Mode: Operate. Refine the existing blue/white engineering workbench and its original-image toolbar. Keep native text buttons after 100%, with left/right quarter turns. Wrap controls at narrow widths; no new modal, animation, palette or visual assets. Remove only the three summary status/ERP/missing-field cards; keep type, drawing name and drawing number editors and all internal validation.

Rotate the bitmap, anchors, leaders and bubble positions together while preserving the viewport center and zoom. Numbers stay upright and circles keep their 15px radius. Original-source coordinates remain the sole saved positions. Dragging, keyboard movement and manual placement use the same inverse mapping. Keep parameter nodes and local input intact; redraw only the viewport and annotation layer.

Angles are session-only, keyed by review/source and PDF page. Restore per-page angles during the current preview; reset on closing, changing orders or reloading. Fit and focus use the oriented dimensions; unavailable images disable rotation.

Disposition: ship. Mock-browser functional tests cover all four orientations, center/scale/layout and document invariants, native drag/keyboard/placement saves, focus, page memory, order/close/reload reset and load failures. Desktop1440 and390px captures were inspected as a batch, followed by one final batch showing the retained summary editors. Captures are in ignored outputs/drawing-rotation-qa. No cloud recognition or real-order edits in QA.

The detector ran once with degraded regex-only coverage. It reported existing accent stripes and sidebar layout transitions outside this scope, with no new findings on the rotation controls. Computed contrast was unavailable; screenshots and native-control behavior were checked. No further visual polish pass is required.
