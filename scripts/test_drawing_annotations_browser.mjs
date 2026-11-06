import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CODEX_NODE_MODULES ? path.join(process.env.CODEX_NODE_MODULES, "playwright") : "C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const rows = process.argv.includes("--rows"), multi = rows || process.argv.includes("--multi"), v3 = process.argv.includes("--v3"), real = multi || v3 || process.argv.includes("--real"), qa = path.resolve(multi ? "outputs/multi-spec-annotation-qa" : v3 ? "outputs/annotation-v3-qa" : "outputs/annotation-qa");
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
let fixtures;
if (multi) {
  fixtures = JSON.parse(fs.readFileSync(path.join(qa, rows ? "rows-browser.json" : "browser.json"), "utf8")).map(f => ({...f, mime:"image/png", image:fs.readFileSync(path.join(qa,rows ? "rows.png" : "source.png"))}));
} else if (v3) {
  fixtures = ["94372f98ae61", "c90288992d76", "0a96d83d903c", "a5730d90908d", "137090949f86"].map((id) => ({
    id, image: fs.readFileSync(path.join(qa, id, "annotation_ocr_pages/page-1.png")), mime: "image/png",
    review: JSON.parse(fs.readFileSync(path.join(qa, id, "annotation_qa_snapshot.json"), "utf8")),
    annotations: JSON.parse(fs.readFileSync(path.join(qa, id, "v3.json"), "utf8")),
  }));
} else if (real) {
  fixtures = [["137090949f86", "spring10.jpg"], ["a5730d90908d", "order2.png"]].map(([id, image]) => ({
    id, image: fs.readFileSync(path.join(qa, image)), mime: image.endsWith("jpg") ? "image/jpeg" : "image/png",
    review: JSON.parse(fs.readFileSync(path.join(qa, `${id}-review.json`), "utf8")),
    annotations: JSON.parse(fs.readFileSync(path.join(qa, `${id}.json`), "utf8")),
  }));
} else {
  const cases = JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe", ["scripts/test_solidworks_export.py", "--json"], { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 }));
  const fields = ["material", "standard_no", "accuracy_grade", "wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length", "solid_height", "total_coils", "active_coils", "surface_roughness_ra", "handedness", "end_type", "end_grinding"];
  fixtures = [{ id: "annotation-browser-demo", review: cases[0].review, mime: "image/svg+xml", image: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="850"><rect width="1200" height="850" fill="white"/><text x="40" y="40">ANNOTATION REGRESSION / SYNTHETIC TEST DATA</text></svg>'),
    annotations: { schema_version: "original_annotations/v1", algorithm_version: "original_annotation_locator/v2", source_document_id: "demo", annotation_revision: 1, pages: [{ page: 1, width: 1200, height: 850, image_url: "/fixture/demo" }], warnings: [], text_obstacles: [],
      annotations: fields.map((field, i) => ({ field, annotation_id: field, label: field, number: i + 1, original_value: cases[0].review.spring_parameters[field]?.value, status: "located", reason: "", locations: [{ location_id: `${field}-demo`, source: "ocr", page: 1, anchor: { x: .18 + i % 4 * .18, y: .18 + Math.floor(i / 4) * .18 }, bubble: { x: .2 + i % 4 * .18, y: .16 + Math.floor(i / 4) * .18 } }] })) } }];
}
const displayFields = ["material", "accuracy_grade", "wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length", "total_coils", "active_coils", "surface_roughness_ra", "handedness", "end_type", "end_grinding"];
if (!real) {
  const doc=fixtures[0].annotations;
  doc.pages.push({page:2,width:1200,height:850,image_url:"/fixture/demo/2"});
  for (const field of ["free_length","surface_roughness_ra"]) {
    const a=doc.annotations.find(a=>a.field===field);
    a.locations.push({location_id:field+"-page2",page:2,source:"manual",anchor:{x:.3,y:.4},bubble:{x:.45,y:field==="free_length"?.3:.55}});
  }
  doc.annotations.find(a=>a.field==="standard_no").locations[0].source="manual";
  doc.annotations.find(a=>a.field==="solid_height").locations[0].source="manual";
  fixtures[0].review.spring_parameters.solid_height = {
    value: "", unit: "mm", source: ["human_edited"], value_kind: "input_height", need_human_review: true,
  };
}
const frontend = path.resolve("frontend");
if (v3) for (const fixture of fixtures) fixture.annotations.pages.forEach((p) => { p.image_url = `/fixture/${fixture.id}/${p.page}`; });
const server = http.createServer((request, response) => {
  const file = path.resolve(frontend, new URL(request.url, "http://localhost").pathname.slice(1) || "index.html");
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return response.writeHead(404).end();
  response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
  response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
fs.mkdirSync(qa, { recursive: true });
let browser;
try {
  browser = await chromium.launch({ headless: true, channel: process.env.UNIT_TEST_BROWSER_CHANNEL || "msedge" });
  for (const fixture of fixtures) {
    let saved = structuredClone(fixture.annotations), persistedReview = structuredClone(fixture.review), reviewRevision = 1, locationSaves = 0, parameterSaves = 0, failNext = false, failBackfill = false, backfills = 0;
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = [], calls = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/*", async (route) => {
      const request = route.request(), apiPath = new URL(request.url()).pathname;
      calls.push(apiPath);
      if (apiPath.startsWith("/fixture/") || apiPath.includes("/artifacts/")) return route.fulfill({ contentType: fixture.mime, body: fixture.image });
      if (!apiPath.startsWith("/api/")) return route.continue();
      let body;
      if (apiPath.endsWith("/annotations/relocalize")) {
        backfills++;
        if (failBackfill) { failBackfill = false; return route.fulfill({ status: 503, json: { detail: "模拟补定位失败" } }); }
        const input = request.postDataJSON();
        assert.equal(input.expected_annotation_revision, saved.annotation_revision);
        assert.equal(input.source_document_id, saved.source_document_id);
        saved.annotation_revision++;
        body = saved;
      } else if (apiPath.endsWith("/annotations")) {
        if (request.method() === "PATCH") {
          if (failNext) { failNext = false; return route.fulfill({ status: 503, json: { detail: "模拟保存失败" } }); }
          const input = request.postDataJSON();
          assert.equal(input.expected_annotation_revision, saved.annotation_revision);
          assert.equal(input.source_document_id, saved.source_document_id);
          for (const c of input.changes) {
            const a = saved.annotations.find((a) => a.annotation_id === c.annotation_id);
            const l = a.locations.find((l) => l.location_id === c.location_id);
            Object.assign(l, c, { source: "manual" });
          }
          saved.annotation_revision++; locationSaves++;
        }
        body = saved;
      } else if (apiPath === `/api/reviews/${fixture.id}`) {
        if (request.method() === "PATCH") {
          const input=request.postDataJSON();assert.equal(input.expected_revision,reviewRevision);
          persistedReview=input.review;parameterSaves++;
          body={review_revision:++reviewRevision,events:(input.events || []).map(e=>({...e,sync_status:"saved"}))};
        } else body = { ...persistedReview, job_id: fixture.id, review_revision: reviewRevision, image_url: saved.pages[0].image_url };
      } else if (apiPath === "/api/material-catalog") body = catalog;
      else if (apiPath === "/api/session") body = { identity: { user_id: "demo", username: "原图气泡回归" }, mode: "mock" };
      else if (apiPath === "/api/reviews") body = { reviews: [{ job_id: fixture.id, drawing_name: fixture.id, image_url: saved.pages[0].image_url, revision: 1 }] };
      else if (apiPath.endsWith("/changes")) body = { events: [] };
      else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
      else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "needs_confirmation", warnings: [], missing_fields: [], pending_fields: [] }, generation_queue_available: false };
      else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [] } };
      else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
      return route.fulfill({ json: body });
    });
    await page.goto(process.env.ANNOTATION_TEST_BASE_URL || `http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction((id) => state.recentReviews.some((r) => r.job_id === id), fixture.id);
    await page.evaluate(async (id) => { await openPersistedReview(id); state.compareTab = "parameters"; renderCompareOverlay(); }, fixture.id);
    try {
      await page.waitForFunction(() => DrawingAnnotations.entry()?.document && document.querySelector("#compareImage")?.naturalWidth && document.querySelectorAll(".annotation-bubble").length, null, { timeout: 10000 });
    } catch (error) {
      console.error({ errors, calls: calls.slice(-15), state: await page.evaluate(() => ({ job: state.lastJob, entry: DrawingAnnotations.entry(), src: document.querySelector("#compareImage")?.src, width: document.querySelector("#compareImage")?.naturalWidth })) });
      throw error;
    }
    // Old saved fixtures may queue unrelated calculation-recovery audits on open.
    // Settle that real save path before measuring the read-only numbering/gesture checks.
    await page.evaluate(()=>flushReviewPersistence({throwOnError:true}));
    const baselineParameterSaves=parameterSaves;
    if(!real)assert.equal(baselineParameterSaves,0);
    const expected = saved.annotations.filter(a=>displayFields.includes(a.field)).reduce((n,a)=>n+a.locations.filter(l=>l.page===1).length,0);
    const originalAnnotations=JSON.parse(JSON.stringify(saved));
    const verifyNumbers=async()=>{
      const pairs=await page.locator('.parameter-annotation-number').evaluateAll(es=>es.map(e=>[e.dataset.annotationField,e.textContent.trim()]));
      for(const [field,text] of pairs)assert.equal(text,String(displayFields.indexOf(field)+1));
      assert.ok(pairs.some(([f,n])=>f==="accuracy_grade" && n==="2"));
      assert.equal(await page.locator('.annotation-bubble[data-annotation-id="standard_no"]').count(),0);
      assert.equal(await page.locator('.annotation-bubble[data-annotation-id="solid_height"]').count(),0);
      for(const [field,number] of displayFields.map((f,i)=>[f,String(i+1)])) {
        const bubbles=page.locator(`.annotation-bubble[data-annotation-id="${field}"]`);
        for(const b of await bubbles.all()) {
          assert.equal(await b.locator('text').textContent(),number);
          assert.ok((await b.getAttribute('aria-label')).startsWith(number+' '));
        }
      }
    };
    await verifyNumbers();
    assert.deepEqual(await page.evaluate(()=>DrawingAnnotations.entry().document),originalAnnotations,"Legacy numbering stays untouched in the cached document");
    assert.equal(locationSaves,0);assert.equal(parameterSaves,baselineParameterSaves);assert.equal(backfills,0,"Renumbering does not request relocalization");
    if(!real){
      const advanced = page.locator('#compareOverlay [data-compare-panel="parameters"] .advanced-parameters');
      const firstAdvanced = advanced.locator('[data-kind="param"]').first();
      assert.equal(await advanced.evaluate(el => el.open), false);
      assert.equal(await firstAdvanced.getAttribute('data-field'), 'solid_height');
      assert.equal(await firstAdvanced.locator('.parameter-annotation-number').count(), 0);
      await page.evaluate(() => focusMissingStandardizationField('solid_height'));
      await page.waitForFunction(() => document.activeElement?.closest('[data-kind="param"][data-field="solid_height"]'));
      assert.equal(await advanced.evaluate(el => el.open), true);
      assert.equal(await firstAdvanced.locator('[data-role="value"]').inputValue(), '');
      assert.equal(parameterSaves, baselineParameterSaves);
      assert.equal(locationSaves, 0);
      await advanced.locator('summary').click();
      const pairs=await page.locator('#compareOverlay [data-compare-panel="parameters"] .parameter-annotation-number').evaluateAll(es=>es.map(e=>[e.dataset.annotationField,e.textContent.trim()]));
      assert.deepEqual(pairs,displayFields.map((f,i)=>[f,String(i+1)]));
      await page.locator('[data-annotation-page]').selectOption('2');
      await page.waitForFunction(()=>DrawingAnnotations.entry().page===2 && document.querySelector('#compareImage')?.complete);
      assert.equal(await page.locator('.annotation-bubble').count(),2);
      await verifyNumbers();
      assert.deepEqual(await page.locator('.annotation-bubble text').allTextContents(),['7','10'],"A sparse page keeps parameter numbers instead of renumbering its bubbles");
      await page.locator('[data-annotation-page]').selectOption('1');
      await page.waitForFunction(()=>DrawingAnnotations.entry().page===1 && document.querySelector('#compareImage')?.complete);
      assert.deepEqual(await page.evaluate(()=>DrawingAnnotations.entry().document),originalAnnotations);
      assert.equal(locationSaves,0);assert.equal(parameterSaves,baselineParameterSaves);
    }
    await page.evaluate(async () => { await document.querySelector('#compareImage').decode(); await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); });
    assert.equal(await page.locator(".annotation-bubble").count(), expected);
    const verifyAnchors = () => page.evaluate(() => {
      const image = document.querySelector("#compareImage"), view = state.compareView;
      const locations = DrawingAnnotations.entry().document.annotations.filter(a=>DrawingAnnotations.numberForField(a.field)!=null).flatMap((a) => a.locations.filter((l) => l.page === DrawingAnnotations.entry().page));
      const anchors = [...document.querySelectorAll(".annotation-anchor")];
      return locations.every((l, i) => {
        const anchor = anchors[i], bubble = anchor.nextElementSibling;
        const ax = Number(anchor.getAttribute("cx")), ay = Number(anchor.getAttribute("cy"));
        const matrix = bubble.transform.baseVal.consolidate().matrix;
        const distance = Math.hypot(ax - matrix.e, ay - matrix.f);
        const line = anchor.previousElementSibling;
        if (distance > 15) {
          if (line?.tagName !== "line") return false;
          const x = Number(line.getAttribute("x2")), y = Number(line.getAttribute("y2"));
          if (Math.abs(Math.hypot(x - matrix.e, y - matrix.f) - 15) > .001
            || Math.abs(Math.hypot(ax - x, ay - y) + 15 - distance) > .001
            || Number(line.getAttribute("x1")) !== ax || Number(line.getAttribute("y1")) !== ay) return false;
        } else if (line?.tagName === "line") return false;
        const p=DrawingAnnotations.viewTransform.project(l.anchor,image.naturalWidth,image.naturalHeight,view);
        return Math.abs(ax-p.x)<.001 && Math.abs(ay-p.y)<.001;
      });
    });
    assert.equal(await verifyAnchors(), true, "Evidence anchors stay fixed and leaders stop at circle edges");
    const verifyColors = async (width) => {
      const beforeDocument = await page.evaluate(() => JSON.stringify(DrawingAnnotations.entry().document));
      const beforeRevision = saved.annotation_revision, beforeSaves = locationSaves;
      const geometry = () => page.evaluate(() => [...document.querySelectorAll('.drawing-annotation-layer line, .annotation-anchor, .annotation-bubble, .annotation-bubble circle, .annotation-bubble text')].map((element) => ({
        attributes: [...element.attributes].map(({ name, value }) => [name, value]),
        fontSize: getComputedStyle(element).fontSize, fontWeight: getComputedStyle(element).fontWeight,
        strokeWidth: getComputedStyle(element).strokeWidth,
      })));
      const resetSelection = async () => {
        await page.mouse.move(0, 0);
        await page.evaluate(() => {
          document.activeElement?.blur();
          DrawingAnnotations.entry().selected = '';
          refreshCompareViewer();
          fitCompareImage();
        });
      };
      await resetSelection();
      const currentGeometry = await geometry();
      const previousPalette = await page.addStyleTag({ content: '.annotation-bubble circle {fill:#2452cb;stroke:#fff}.annotation-bubble text {fill:#fff}.annotation-bubble:hover circle,.annotation-bubble:focus-visible circle,.annotation-bubble.selected circle {fill:#14388f;stroke:#e9a800}' });
      assert.deepEqual(await geometry(), currentGeometry, 'changing only the palette never changes SVG geometry or typography');
      await previousPalette.evaluate((element) => element.remove());
      const bubble = page.locator('.annotation-bubble[data-annotation-id="free_length"]').first();
      const colors = () => bubble.evaluate((element) => {
        const circle = getComputedStyle(element.querySelector('circle')), text = getComputedStyle(element.querySelector('text'));
        return { fill: circle.fill, border: circle.stroke, text: text.fill, strokeWidth: circle.strokeWidth, opacity: getComputedStyle(element).opacity };
      });
      assert.deepEqual(await colors(), { fill: 'rgba(0, 0, 0, 0)', border: 'rgb(36, 82, 203)', text: 'rgb(36, 82, 203)', strokeWidth: '2px', opacity: '1' });
      if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.screenshot({ path: path.join(qa, `${fixture.id}-${width}-transparent.png`) });
      const emphasized = { fill: 'rgba(36, 82, 203, 0.12)', border: 'rgb(233, 168, 0)', text: 'rgb(20, 56, 143)', strokeWidth: '3px', opacity: '1' };
      await bubble.hover();
      assert.deepEqual(await colors(), emphasized);
      await page.mouse.move(0, 0);
      await page.keyboard.press('Tab');
      await bubble.focus();
      assert.equal(await bubble.evaluate((element) => element.matches(':focus-visible')), true);
      assert.deepEqual(await colors(), emphasized);
      await bubble.press('Enter');
      await page.waitForFunction(() => document.activeElement?.closest('[data-field="free_length"]'));
      await page.mouse.move(0, 0);
      await page.evaluate(() => { document.activeElement?.blur(); DrawingAnnotations.renderLayer(); });
      assert.deepEqual(await colors(), emphasized, 'selection remains emphasized after hover and focus end');
      if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.screenshot({ path: path.join(qa, `${fixture.id}-${width}-selected.png`) });
      for (const point of [{ x: 0, y: 0 }, { x: 0, y: -9 }, { x: 14, y: 0 }]) {
        await resetSelection();
        const box = await bubble.boundingBox();
        await page.mouse.click(box.x + box.width / 2 + point.x, box.y + box.height / 2 + point.y);
        await page.waitForFunction(() => DrawingAnnotations.entry().selected === 'free_length');
        await page.waitForFunction(() => document.activeElement?.closest('[data-field="free_length"]'));
      }
      await resetSelection();
      assert.deepEqual(await geometry(), currentGeometry);
      assert.equal(await page.evaluate(() => JSON.stringify(DrawingAnnotations.entry().document)), beforeDocument, 'color and selection never edit saved locations');
      assert.equal(saved.annotation_revision, beforeRevision);
      assert.equal(locationSaves, beforeSaves, 'palette and click checks do not save annotations');
      assert.equal(parameterSaves, baselineParameterSaves);
    };
    assert.equal(await verifyAnchors(), true);
    const beforeRotation=JSON.stringify(saved);
    for (let turn=0;turn<4;turn++) {
      await page.locator('[data-view-action="rotate-right"]').click();
      await verifyNumbers();assert.equal(await verifyAnchors(),true);
      assert.equal(await page.locator('.annotation-bubble text').first().evaluate(e=>{const m=e.getScreenCTM();return m.a>0 && Math.abs(m.b)<.001 && Math.abs(m.c)<.001 && m.d>0;}),true);
    }
    assert.equal(JSON.stringify(saved),beforeRotation);assert.equal(locationSaves,0);assert.equal(parameterSaves,baselineParameterSaves);
    failBackfill = true;
    const beforeBackfill = structuredClone(saved.annotations);
    await page.locator('[data-annotation-action="relocalize"]').click();
    await page.waitForFunction(() => DrawingAnnotations.entry()?.error?.includes("模拟补定位失败"));
    assert.deepEqual(saved.annotations, beforeBackfill);
    await page.locator('[data-annotation-action="relocalize"]').click();
    await page.waitForFunction(() => DrawingAnnotations.entry()?.phase === "saved" && !DrawingAnnotations.entry()?.relocalizing);
    assert.equal(backfills, 2);
    assert.deepEqual(saved.annotations, beforeBackfill);
    await page.locator('[data-view-action="zoom-in"]').click();
    assert.equal(await verifyAnchors(), true);
    await page.locator('[data-view-action="fit"]').click();
    const beforePan = await page.evaluate(() => ({ key: DrawingAnnotations.entry().layout.key, x: state.compareView.x }));
    const viewport = await page.locator("#compareViewport").boundingBox();
    await page.mouse.move(viewport.x + 35, viewport.y + 35);
    await page.mouse.down(); await page.mouse.move(viewport.x + 60, viewport.y + 55, { steps: 3 }); await page.mouse.up();
    assert.equal(await page.evaluate(() => DrawingAnnotations.entry().layout.key), beforePan.key, "pan reuses the layout");
    assert.equal(await verifyAnchors(), true);
    await page.locator('[data-view-action="fit"]').click();
    await page.locator('.annotation-bubble[data-annotation-id="free_length"]').first().click();
    await page.waitForFunction(() => document.activeElement?.closest('[data-field="free_length"]'));
    await page.locator('[data-annotation-action="edit"]').click();
    const bubble = page.locator('.annotation-bubble[data-annotation-id="wire_diameter"]').first();
    const before = await page.evaluate(() => structuredClone(DrawingAnnotations.entry().document.annotations.find((a) => a.field === "wire_diameter").locations[0]));
    const point = await bubble.boundingBox();
    failNext = true;
    await page.mouse.move(point.x + point.width / 2, point.y + point.height / 2);
    await page.mouse.down(); await page.mouse.move(point.x + point.width / 2 + 40, point.y + point.height / 2 - 25, { steps: 4 }); await page.mouse.up();
    await page.waitForFunction(() => DrawingAnnotations.entry().phase === "failed");
    await page.locator('[data-annotation-action="retry"]').click();
    await page.waitForFunction(() => DrawingAnnotations.entry().phase === "saved");
    const after = saved.annotations.find((a) => a.field === "wire_diameter").locations[0];
    assert.deepEqual(after.anchor, before.anchor, "drag only changes the bubble");
    assert.notDeepEqual(after.bubble, before.bubble);
    assert.equal(after.source, "manual");
    assert.equal(locationSaves, 1);
    assert.equal(parameterSaves, baselineParameterSaves, "bubble gestures never save parameters");
    await page.reload();
    await page.waitForFunction((id) => state.recentReviews.some((r) => r.job_id === id), fixture.id);
    await page.evaluate(async (id) => { await openPersistedReview(id); state.compareTab = "parameters"; renderCompareOverlay(); }, fixture.id);
    await page.waitForFunction(() => DrawingAnnotations.entry()?.document && document.querySelectorAll(".annotation-bubble").length);
    assert.deepEqual(await page.evaluate(() => DrawingAnnotations.entry().document.annotations.find((a) => a.field === "wire_diameter").locations[0].bubble), after.bubble);
    assert.equal(await verifyAnchors(), true);
    await verifyNumbers();
    for (const width of [1440, 430]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.locator('[data-view-action="fit"]').click();
      assert.equal(await page.locator(".annotation-bubble").count(), expected, "narrow panels never hide annotations");
      assert.equal(await verifyAnchors(), true);
      await verifyColors(width);
      if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.screenshot({ path: path.join(qa, `${fixture.id}-${width}.png`) });
    }
    await page.locator('[data-view-action="rotate-right"]').click();
    await page.locator('[data-annotation-action="edit"]').click();
    const keyBubble=page.locator('.annotation-bubble[data-annotation-id="wire_diameter"]').first();
    await keyBubble.focus();
    // Adopt the actual visual position first; this legacy location is already manual.
    const keyboardStart=await page.evaluate(()=>{const a=DrawingAnnotations.entry().document.annotations.find(a=>a.field==="wire_diameter");return DrawingAnnotations.screenPoint(a.locations[0].bubble);});
    const savedCount=locationSaves, keyboardRevision=saved.annotation_revision;
    await keyBubble.press('ArrowRight');
    await page.waitForFunction(n=>DrawingAnnotations.entry().phase==="saved" && DrawingAnnotations.entry().document.annotation_revision>n,keyboardRevision);
    await page.waitForFunction(()=>!DrawingAnnotations.entry().pending.size && DrawingAnnotations.entry().phase==="saved");
    const keyboardEnd=await page.evaluate(()=>{const a=DrawingAnnotations.entry().document.annotations.find(a=>a.field==="wire_diameter");return DrawingAnnotations.screenPoint(a.locations[0].bubble);});
    assert.ok(Math.abs(keyboardEnd.x-keyboardStart.x-5)<.01 && Math.abs(keyboardEnd.y-keyboardStart.y)<.01);
    assert.equal(locationSaves,savedCount+1);assert.equal(parameterSaves,baselineParameterSaves);
    await verifyNumbers();
    if (!real) {
      await page.evaluate(() => focusMissingStandardizationField('solid_height'));
      const row = page.locator('#compareOverlay .advanced-parameters [data-kind="param"][data-field="solid_height"]');
      const height = row.locator('[data-role="value"]');
      await height.fill('7.25');
      await height.press('Tab');
      await row.locator('[data-role="confirm"]').click();
      await page.evaluate(() => flushReviewPersistence({throwOnError:true}));
      assert.equal(Number(persistedReview.spring_parameters.solid_height.value), 7.25);
      assert.equal(persistedReview.spring_parameters.solid_height.need_human_review, false);
      assert.deepEqual(saved.annotations.find(a => a.field === 'solid_height'), originalAnnotations.annotations.find(a => a.field === 'solid_height'));
      await page.reload();
      await page.waitForFunction((id) => state.recentReviews.some((r) => r.job_id === id), fixture.id);
      await page.evaluate(async (id) => { await openPersistedReview(id); focusMissingStandardizationField('solid_height'); }, fixture.id);
      assert.equal(await height.inputValue(), '7.25');
      await verifyNumbers();
    }
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(`drawing annotation browser tests passed (${fixtures.length} ${real ? "local drawings" : "synthetic fixture"}): 13 display numbers, hidden Hb and standard, advanced Hb focus/save, legacy cache, sparse pages, rotation/keyboard, backfill/retry and manual positions`);
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
