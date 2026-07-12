import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const start = appSource.indexOf("function latestStandardizationChatApplication");
const end = appSource.indexOf("function normalizeActionValue", start);

assert.notEqual(start, -1, "chat application rollback helpers must exist");
assert.notEqual(end, -1, "chat application rollback helper block must be complete");

const context = {
  state: { review: null, activeReviewMessageId: null },
  structuredClone,
  targetFieldLabel: (field) => field,
  escapeHtml: (value) => String(value),
  syncBubbleValue: () => {},
  getReviewContext: () => null,
};
vm.createContext(context);
vm.runInContext(appSource.slice(start, end), context);

const pendingAction = {
  type: "propose_parameter_patch",
  target_field: "outer_diameter",
  proposed_value: 22,
  status: "pending",
  apply_policy: "manual_confirm_required",
};

context.state.review = {
  spring_parameters: {
    outer_diameter: { value: 22, unit: "mm", source: ["standardization_chat"] },
  },
  manual_confirmations: {
    standardization_chat_outer_diameter: { confirmed: true, value: 22 },
  },
  standardization_chat: [{ created_at: "turn-1", suggested_actions: [{ ...pendingAction, status: "applied" }] }],
  agent_actions: [{
    id: "chat-apply-1",
    source: "standardization_chat",
    turn_created_at: "turn-1",
    applied_patches: [{
      action_type: "propose_parameter_patch",
      target_field: "outer_diameter",
      proposed_value: 22,
    }],
    rollback: {
      turn_created_at: "turn-1",
      turn_index: 0,
      field_states: [{
        target: "outer_diameter",
        kind: "parameter",
        exists: true,
        value: { value: 20, unit: "mm", source: ["qwen"] },
        confirmation_key: "standardization_chat_outer_diameter",
        confirmation: { exists: false, value: null },
      }],
      action_states: [{ index: 0, value: pendingAction }],
    },
  }],
};

const reverted = context.undoStandardizationChatApplication("chat-apply-1");
assert.equal(reverted.ok, true);
assert.equal(context.state.review.spring_parameters.outer_diameter.value, 20);
assert.equal(context.state.review.manual_confirmations.standardization_chat_outer_diameter, undefined);
assert.equal(context.state.review.standardization_chat[0].suggested_actions[0].status, "pending");
assert.equal(context.state.review.agent_actions[0].reverted, true);

context.state.review.agent_actions[0].reverted = false;
context.state.review.spring_parameters.outer_diameter.value = 24;
const conflict = context.undoStandardizationChatApplication("chat-apply-1");
assert.equal(conflict.ok, false);
assert.equal(context.state.review.spring_parameters.outer_diameter.value, 24);

const supplementStart = appSource.indexOf("function canBatchSupplementChatAction");
const supplementEnd = appSource.indexOf("function renderStandardizationChatBatchHtml", supplementStart);
assert.notEqual(supplementStart, -1, "batch supplement helpers must exist");
assert.notEqual(supplementEnd, -1, "batch supplement helper block must be complete");
vm.runInContext(appSource.slice(supplementStart, supplementEnd), context);

assert.equal(context.canBatchSupplementChatAction({
  type: "request_missing_field",
  target_field: "active_coils",
  status: "need_input",
}), true);
assert.equal(context.canBatchSupplementChatAction({
  type: "request_missing_field",
  target_field: "technical_requirements.1",
  status: "need_input",
}), false);
assert.equal(context.supplementInputMode("active_coils"), "decimal");
assert.equal(context.supplementInputMode("end_grinding"), "text");
const supplementForm = context.renderStandardizationChatSupplementFormHtml([
  { action: { target_field: "active_coils", target_label: "有效圈数", reason: "补充后可计算" }, actionIndex: 0 },
  { action: { target_field: "end_grinding", target_label: "端面磨削" }, actionIndex: 1 },
], 3);
assert.match(supplementForm, /data-kind="chat_supplement_form"/);
assert.match(supplementForm, /data-field="active_coils"/);
assert.match(supplementForm, /data-field="end_grinding"/);

console.log("standardization chat UI rollback and batch supplement test passed");
