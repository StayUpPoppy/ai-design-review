import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = process.env.CODEX_NODE_MODULES
  ? require(path.join(process.env.CODEX_NODE_MODULES, "playwright"))
  : require("C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const root = path.resolve("frontend");
const output = path.resolve("outputs/translation-ui-qa");
const warningFixtures = JSON.parse(fs.readFileSync("scripts/fixtures/technical_translation_warning_pairs.json", "utf8"));
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((request, response) => {
  const file = path.resolve(root, request.url.split("?")[0].replace(/^\//, "") || "index.html");
  if (!file.startsWith(root + path.sep) && file !== path.join(root, "index.html")) { response.writeHead(403).end(); return; }
  if (!fs.existsSync(file)) { response.writeHead(404).end(); return; }
  response.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : file.endsWith(".js") ? "text/javascript" : "text/html");
  response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true, ...(process.env.TRANSLATION_TEST_BROWSER_CHANNEL ? { channel: process.env.TRANSLATION_TEST_BROWSER_CHANNEL } : {}) });
try {
  for (const [size, width] of [["desktop", 1440], ["mobile", 390]]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let revision = 1, translationCount = 0, revalidationCount = 0, retryWorks = false;
    let review = { drawing_summary: { drawing_name: "翻译回归演示（模拟测试数据）", drawing_no: "DEMO-TRANSLATION", spring_type: "compression_spring" },
      spring_parameters: {}, technical_requirements: [
        { requirement_id: "foreign", type: "process", content: "Shear modulus G* = 80000 MPa", need_human_review: false },
        { requirement_id: "failed", type: "other", content: "Manufacturing and technical characteristics per GOST 9389-75 (Wire B-1-1.5 GOST 9389-75)", need_human_review: false },
        { requirement_id: "historical-3d", type: "other", content: "7.未注尺寸以3D为准", original_content: "7.未注尺寸以3D为准",
          source_language: "zh", translation_source: "qwen_text:old", source: ["qwen_vision"], need_human_review: true,
          translation_status: "failed", translation_error: "译文仍包含外语说明，请重试或人工填写中文。",
          translation_input_snapshot: { content: "7.未注尺寸以3D为准", type: "other" } },
        { requirement_id: "unsafe", type: "other", content: "热处理300°C", original_content: "Heat treatment 300°C",
          need_human_review: true, translation_status: "failed", translation_error: "翻译改变了数值或公差，原文已保留，请核对后重试。",
          translation_input_snapshot: { content: "热处理300°C", type: "other" } },
        { requirement_id: "r9", type: "process", original_number: "9", content: "9. Заневолить силой F₃ с выдержкой под нагрузкой не менее 6 часов", original_content: "9. Заневолить силой F₃ с выдержкой под нагрузкой не менее 6 часов", source: ["qwen_vision"], need_human_review: true,
          translation_status: "failed", translation_error: "翻译改变了公式变量", translation_input_snapshot: { content: "9. Заневолить силой F₃ с выдержкой под нагрузкой не менее 6 часов", type: "process" } },
        { requirement_id: "r12-edited", type: "surface", original_number: "12", content: "Покрытие Ц15.hr ГОСТ 9306-85（人工补充）", original_content: "Покрытие Ц15.hr ГОСТ 9306-85", source: ["qwen_vision", "human_edited"], need_human_review: true,
          translation_status: "failed", translation_error: "译文仍包含外语说明", translation_input_snapshot: { content: "Покрытие Ц15.hr ГОСТ 9306-85（人工补充）", type: "surface" } },
        { requirement_id: "chinese", type: "heat_treatment", content: "热处理 300°C+10°C/20min+1min", need_human_review: false }],
      manual_confirmations: {}, change_history: [], standardization_results: [], drawing_annotations: null };
    review.technical_requirements.push(...warningFixtures.map((fixture) => ({ requirement_id: `warning-${fixture.original_number}`,
      type: fixture.type, original_number: fixture.original_number, content: fixture.original_content, original_content: fixture.original_content,
      source: ["qwen_vision"], need_human_review: true, translation_status: "failed", translation_error: "历史工程信息不一致",
      translation_input_snapshot: { content: fixture.original_content, type: fixture.type } })));
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const apiPath = url.pathname;
      let body = {};
      if (request.method() === "PATCH" && apiPath === "/api/reviews/test-order") {
        const input = request.postDataJSON();
        review = input.review;
        revision++;
        body = { review_revision: revision, events: input.events.map((item) => ({ ...item, sync_status: "saved" })) };
      } else if (apiPath.endsWith("/technical-requirements/recover-preview")) {
        assert.equal(request.postDataJSON().expected_revision, revision);
        body = { job_id: "test-order", based_on_revision: revision, source: "qwen_vision_raw", message: "请选择需要补回的条目；补回后仍需人工确认。", order_hints: [], items: [
          { status: "available", reason: "原始识别记录中存在，当前列表未保留。", requirement: { requirement_id: "recovered-nine", recognition_key: "raw-nine", original_number: "9", source_order: 9, page: 1,
            type: "process", content: "施加力 F3 并保持负载不少于 6 小时", original_content: "9. Заневолить силой F3 с выдержкой под нагрузкой не менее 6 часов", source_language: "ru", translation_status: "translated", need_human_review: true } },
          { status: "possible_existing", reason: "可能已存在或被人工改写，请核对后选择。", requirement: { requirement_id: "recovered-ten", recognition_key: "raw-ten", original_number: "10", source_order: 10, page: 1,
            type: "process", content: "强压后检查残余变形", original_content: "10. Определить остаточную деформацию", source_language: "ru", translation_status: "translated", need_human_review: true } }
        ] };
      } else if (apiPath.endsWith("/technical-requirements/translate")) {
        const mode = request.postDataJSON().mode || "translate";
        if (mode === "revalidate") revalidationCount++; else translationCount++;
        await new Promise((resolve) => setTimeout(resolve, 100));
        body = { job_id: "test-order", based_on_revision: revision, requirements: request.postDataJSON().requirements.map((row) => {
          if (mode === "revalidate") {
            const item = review.technical_requirements.find((item) => item.requirement_id === row.requirement_id);
            const result = { ...row, content: item.content, original_content: item.original_content || item.content, translation_status: "failed", translation_error: item.translation_error || "没有可用候选", translation_input_snapshot: row.source_snapshot, recovery_mode: "unavailable" };
            const fixture = warningFixtures.find((fixture) => row.requirement_id === `warning-${fixture.original_number}`);
            if (fixture) return { ...result, content: fixture.content, translation_status: "translated", translation_error: "", source_language: "ru",
              translation_source: "saved_recognition", recovery_mode: "automatic", translation_warnings: [{ code: "engineering_mismatch",
                category: fixture.expected_category, message: "译文中的工程代号与原文不同，请核对后确认。",
                original: fixture.original_number === "11" ? "СТ ЦКБА 030-2006" : "Б-1-1,5",
                translated: fixture.original_number === "11" ? "STsKBA 030-2006" : "B-1-1.5" }],
              translation_warning_snapshot: { content: fixture.content, type: fixture.type } };
            if (row.requirement_id === "historical-3d") return { ...result, translation_status: "not_required", translation_error: "", recovery_mode: "automatic" };
            if (row.requirement_id === "r9") return { ...result, content: "在力 F3 作用下强压处理，保载时间不少于 6 小时", source_language: "ru", translation_status: "translated", translation_error: "", translation_source: "saved_recognition", recovery_mode: "automatic" };
            if (row.requirement_id === "r12-edited") return { ...result, recovery_mode: "preview", recovery_reason: "此条已有人工编辑，请对照后选择；不会自动替换当前文本。", translation_candidates: [{ content: "镀层 Ц15.hr 按 ГОСТ 9306-85 执行", original_content: item.original_content, source_language: "ru", translation_source: "saved_recognition" }] };
            return result;
          }
          assert.notEqual(row.requirement_id, "unsafe", "engineering validation failures cannot be auto-translated");
          if (row.requirement_id === "historical-3d") return { ...row, content: row.source_snapshot.content, original_content: row.source_snapshot.content,
            source_language: "zh", translation_status: "not_required", translation_error: "", translation_source: "qwen_text:old", translation_input_snapshot: row.source_snapshot };
          const failed = row.requirement_id === "failed" && !retryWorks;
          return { ...row, content: failed ? row.source_snapshot.content : (row.requirement_id === "foreign" ? "剪切模量 G* = 80000 MPa" : "制造和技术特性按 GOST 9389-75（钢丝 B-1-1.5 GOST 9389-75）"),
            original_content: row.source_snapshot.content, source_language: "en", translation_status: failed ? "failed" : "translated",
            translation_error: failed ? "翻译改变了标准编号，原文已保留，请核对后重试。" : "", translation_source: "simulated:test", translation_input_snapshot: row.source_snapshot };
        }) };
      } else if (apiPath === "/api/reviews/test-order") {
        body = { ...review, job_id: "test-order", review_revision: revision, image_url: "" };
      } else if (apiPath === "/api/session") {
        body = { identity: { user_id: "demo", username: "模拟测试用户" }, mode: "mock" };
      } else if (apiPath === "/api/reviews") {
        body = { reviews: [] };
      } else if (apiPath.endsWith("/changes")) {
        body = { events: [] };
      } else if (apiPath.endsWith("/generation-jobs")) {
        body = { generation_jobs: [], generation_queue_available: false };
      } else if (apiPath.endsWith("/generation-readiness")) {
        body = { generation_readiness: { status: "needs_input", summary: "演示数据不发起生图", warnings: [], missing_fields: [], pending_fields: [], confirmed_core_count: 0, core_field_count: 8 }, generation_queue_available: false };
      } else if (apiPath.endsWith("/reasonableness")) {
        body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [], summary: "模拟测试数据" } };
      } else if (apiPath.endsWith("/annotations")) {
        body = { schema_version: "original_annotations/v1", source_document_id: "demo", annotation_revision: 1, pages: [], annotations: [], warnings: [] };
      } else {
        body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.evaluate(async () => { await openPersistedReview("test-order"); focusMissingStandardizationField("technical_requirements.foreign"); });
    await page.waitForFunction(() => state.review.technical_requirements.find((item) => item.requirement_id === "foreign").translation_status === "translated" && !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length);
    // Order loading also refreshes history/readiness/annotations. Let those
    // requests finish before asserting keyboard focus on a rerenderable row.
    await page.waitForLoadState("networkidle");
    assert.equal(translationCount, 1, "one order batches its foreign notes");
    assert.equal(revalidationCount, 1, "historical evidence is checked once, separately from paid translation");
    const historical = await page.evaluate(() => state.review.technical_requirements.find((item) => item.requirement_id === "historical-3d"));
    assert.equal(historical.translation_status, "not_required");
    assert.equal(historical.need_human_review, true);
    assert.equal(historical.source_language, "zh");
    assert.deepEqual(historical.source, ["qwen_vision"]);
    assert.equal(review.technical_requirements.find((item) => item.requirement_id === "historical-3d").translation_status, "not_required", "recovery must be persisted");
    assert.ok(review.change_history.some((event) => event.event_type === "technical_requirement_translation_recovered"));
    const block = page.locator(".compare-overlay .technical-requirements-block");
    await block.waitFor({ state: "visible" });
    const warningRow = block.locator('[data-requirement-id="warning-11"]');
    assert.equal(await warningRow.locator('textarea').inputValue(), warningFixtures[0].content);
    assert.equal(await warningRow.locator('[data-role="confirm"]').isEnabled(), true);
    assert.equal(await warningRow.locator('.technical-translation-status').textContent(), "译文与原文存在工程信息差异，请核对后确认。");
    const warningDetails = warningRow.locator('.technical-translation-details');
    assert.equal(await warningDetails.getAttribute('open'), null);
    await warningDetails.locator('summary').press('Enter');
    assert.equal(await warningDetails.getAttribute('open'), "");
    assert.ok((await warningDetails.textContent()).includes('СТ ЦКБА'));
    await warningRow.scrollIntoViewIfNeeded();
    await warningRow.screenshot({ path: path.join(output, `${size}-warnings.png`) });
    assert.equal(await warningRow.evaluate((element) => [...element.querySelectorAll('button, p, summary')].some((control) => control.getBoundingClientRect().right > element.getBoundingClientRect().right + 2)), false);
    assert.equal(await block.locator('[data-requirement-id="foreign"] textarea').inputValue(), "剪切模量 G* = 80000 MPa");
    assert.equal(await block.locator('[data-requirement-id="historical-3d"] textarea').inputValue(), "7.未注尺寸以3D为准");
    assert.equal(await block.locator('[data-requirement-id="historical-3d"] [data-role="confirm"]').isEnabled(), true);
    assert.equal(await block.locator('[data-requirement-id="historical-3d"] [data-translation-action]').count(), 0);
    assert.equal(await block.locator('[data-requirement-id="unsafe"] [data-role="confirm"]').isEnabled(), false);
    assert.equal(await block.locator('[data-requirement-id="r9"] textarea').inputValue(), "在力 F3 作用下强压处理，保载时间不少于 6 小时");
    const edited = block.locator('[data-requirement-id="r12-edited"]');
    assert.equal(await edited.locator('textarea').inputValue(), "Покрытие Ц15.hr ГОСТ 9306-85（人工补充）");
    await edited.locator('.technical-translation-candidates summary').press("Enter");
    assert.equal(await edited.locator('.technical-translation-candidates').getAttribute('open'), "");
    await edited.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, `${size}-translation-candidates.png`) });
    const candidateOverflow = await edited.evaluate((element) => [...element.querySelectorAll('button, summary, p')].some((control) => control.getBoundingClientRect().right > element.getBoundingClientRect().right + 2));
    assert.equal(candidateOverflow, false);
    await edited.getByRole('button', { name: '采用候选译文', exact: true }).click();
    await page.waitForFunction(() => state.review.technical_requirements.find((item) => item.requirement_id === 'r12-edited').translation_status === 'translated' && !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length);
    assert.equal(await edited.locator('textarea').inputValue(), "镀层 Ц15.hr 按 ГОСТ 9306-85 执行");
    assert.equal(await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.technical_requirements_text.includes('Ц15.hr')), false);
    await edited.locator('[data-role="confirm"]').click();
    await page.waitForFunction(() => state.review.technical_requirements.find((item) => item.requirement_id === 'r12-edited').need_human_review === false && !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length);
    assert.equal(await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.technical_requirements_text.includes('Ц15.hr')), true);
    await block.locator('[data-requirement-id="foreign"] summary').press("Enter");
    assert.equal(await block.locator('[data-requirement-id="foreign"] details').getAttribute("open"), "");
    const overflow = await block.evaluate((element) => [...element.querySelectorAll("button, textarea, summary")].some((control) => {
      const a = element.getBoundingClientRect(), b = control.getBoundingClientRect();
      return b.width && (b.right > a.right + 2 || b.left < a.left - 2);
    }));
    assert.equal(overflow, false, "translation controls must fit the sidebar");
    await block.locator('[data-requirement-id="historical-3d"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, `${size}.png`) });
    const packageBefore = await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.technical_requirements_text);
    assert.equal(packageBefore.includes("Shear"), false);
    assert.equal(packageBefore.includes("Manufacturing"), false);
    assert.equal(packageBefore.includes("以3D为准"), false, "recovery alone cannot export an unconfirmed note");
    await block.locator('[data-requirement-id="historical-3d"] [data-role="confirm"]').click();
    await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length && state.review.technical_requirements.find((item) => item.requirement_id === "historical-3d").need_human_review === false);
    assert.equal(await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.technical_requirements_text.includes("以3D为准")), true);
    await block.locator('[data-requirement-id="foreign"] [data-role="confirm"]').click();
    await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length && state.review.technical_requirements.find((item) => item.requirement_id === "foreign").need_human_review === false);
    retryWorks = true;
    await block.locator('[data-requirement-id="failed"] [data-translation-action="translate"]').click();
    await page.waitForFunction(() => state.review.technical_requirements.find((item) => item.requirement_id === "failed").translation_status === "translated" && !state.reviewPersistenceSaving);
    assert.equal(translationCount, 2, "explicit retry translates only the failed note");
    const beforeRecovery = await page.evaluate(() => JSON.stringify(state.review.technical_requirements));
    await block.getByRole("button", { name: "补回遗漏技术要求", exact: true }).click();
    await block.locator('[data-recovery-action="apply"]').waitFor({ state: "visible" });
    assert.equal(await page.evaluate(() => JSON.stringify(state.review.technical_requirements)), beforeRecovery, "preview does not change notes");
    assert.equal(await block.locator('[data-recovery-index="0"]').isChecked(), true);
    assert.equal(await block.locator('[data-recovery-index="1"]').isChecked(), false);
    await block.locator('[data-recovery-index="1"]').check();
    const recoveryOverflow = await block.evaluate((element) => [...element.querySelectorAll(".technical-recovery button, .technical-recovery details, .technical-recovery-choice")].some((control) => {
      const outer = element.getBoundingClientRect(), inner = control.getBoundingClientRect();
      return inner.width && (inner.right > outer.right + 2 || inner.left < outer.left - 2);
    }));
    assert.equal(recoveryOverflow, false, "recovery preview fits narrow sidebar");
    await block.locator(".technical-recovery").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, `${size}-recovery.png`) });
    await block.locator(".technical-recovery").screenshot({ path: path.join(output, `${size}-recovery-panel.png`) });
    await block.locator('[data-recovery-action="apply"]').click();
    await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length && state.review.technical_requirements.some((item) => item.requirement_id === "recovered-ten"));
    assert.equal(await block.locator('[data-requirement-id="recovered-nine"] .technical-original-number').textContent(), "原图第 9 条");
    assert.equal(await page.evaluate(() => state.review.technical_requirements.find((item) => item.requirement_id === "recovered-nine").need_human_review), true);
    assert.equal(await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.technical_requirements_text.includes("残余变形")), false);
    await block.locator('[data-requirement-id="recovered-ten"] [data-role="confirm"]').click();
    await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length && state.review.technical_requirements.find((item) => item.requirement_id === "recovered-ten").need_human_review === false);
    assert.equal(await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.technical_requirements_text.includes("残余变形")), true);
    assert.equal(await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.technical_requirements_text.startsWith("技术要求\n")), false);
    await block.locator('[data-requirement-id="warning-11"] [data-role="confirm"]').click();
    await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length && state.review.technical_requirements.find((item) => item.requirement_id === "warning-11").need_human_review === false);
    assert.equal(await page.evaluate(() => state.review.change_history.some((event) => event.event_type === 'technical_requirement_confirmed' && event.metadata.translation_warning_acknowledgement?.requirement_id === 'warning-11')), true);
    assert.equal(await page.evaluate(() => buildSafeConfirmationPlan(state.review).items.some((entry) => entry.item?.requirement_id === 'warning-13')), true);
    await page.locator('.compare-overlay [data-action="confirm-all-review-items"]').first().click();
    await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length && state.review.technical_requirements.find((item) => item.requirement_id === "warning-13").need_human_review === false);
    assert.equal(await page.evaluate(() => state.review.change_history.some((event) => event.event_type === 'safe_fields_confirmed' && event.metadata.translation_warning_acknowledgements?.some((ack) => ack.requirement_id === 'warning-13'))), true);
    assert.equal(await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.technical_requirements_text.includes('B-1-1.5')), true);
    await page.reload();
    await page.evaluate(async () => { await openPersistedReview("test-order"); focusMissingStandardizationField("technical_requirements.historical-3d"); });
    const reopened = await page.evaluate(() => state.review.technical_requirements.find((item) => item.requirement_id === "historical-3d"));
    assert.equal(reopened.content, "7.未注尺寸以3D为准");
    assert.equal(reopened.need_human_review, false);
    assert.equal(reopened.translation_status, "not_required");
    assert.equal(translationCount, 2, "refresh must not check a recovered note again");
    assert.equal(await page.evaluate(() => state.review.technical_requirements.find((item) => item.requirement_id === 'warning-13').need_human_review), false);
    assert.equal(await page.evaluate(() => TechnicalRequirementTranslation.warnings(state.review.technical_requirements.find((item) => item.requirement_id === 'warning-13')).length), 1);
    assert.equal(await page.evaluate(() => state.review.technical_requirements.filter((item) => item.recognition_key === "raw-ten").length), 1);
    assert.deepEqual(errors, [], `${size} browser must have no uncaught errors`);
    await page.close();
  }
  console.log(`PASS: actual workbench translation, confirmation, retry, keyboard original disclosure and narrow layout. QA screenshots: ${output}`);
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
