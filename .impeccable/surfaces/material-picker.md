# 材料搜索下拉

Mode: Operate. Scoped extension of the existing Chinese engineering review workbench. Primary target: `frontend/material-picker.js`; related targets: `frontend/app.js`, `frontend/styles.css`, `frontend/index.html`.

The engineer selects an existing catalog material without changing engineering data while searching. Preserve the incumbent light surface, blue focus/selection, system Chinese typography and compact parameter row. The visible trigger occupies the original value column; the hidden native select remains the parameter-edit adapter.

The popup has a focused search input above an independently scrolling list. Search names, explicit grades and aliases locally. It is anchored to the trigger, flips above when space below is limited, and fits narrow viewports. The list retains real selected state while keyboard navigation has a separate active highlight. Escape restores trigger focus; Tab leaves without committing. IME Enter does not select. Catalog errors retain the existing retry note.

Opening, typing and dismissal are presentation-only. One real selection uses the existing input/change pipeline once. Close on context replacement, row removal or workbench dismissal. Detached popup events are bound to their owning panel and cannot operate a newly opened picker. Existing raw material evidence and confirmed historical values remain protected.

Verified in Edge at 1440x1000, 1100x900 and 390x900 with labeled mock orders. Desktop/mobile captures in ignored `outputs/material-catalog-qa/material-search-*.png` were visually inspected. Functional coverage includes filtering, empty results, scroll, arrows/Enter, IME, Escape, Tab, outside dismissal, stale events, save retry, original confirmation, new 60Si2MnA calculations and catalog retry focus. Details and deployment checks are in `docs/material-catalog.md`.

Disposition: ship for this material picker. One mechanical detector pass reported 11 existing CSS warnings outside changed rules, preserved in the validation record. No new shipping raster assets or root visual-system replacement. The separate existing API wording and diameter-linkage regression failures are explicitly recorded; no whole-project clean-test claim.
