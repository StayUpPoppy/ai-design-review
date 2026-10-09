import fs from "node:fs";
import vm from "node:vm";

// Legacy UI tests execute isolated app function blocks, not the index.html
// script graph. Load the real shared classifier instead of stubbing it.
export function translationTestHelpers(context) {
  context.window ||= {};
  vm.runInContext(fs.readFileSync(new URL("../frontend/technical-requirement-translation.js", import.meta.url), "utf8"), context);
  context.technicalTranslationService = () => context.window.TechnicalRequirementTranslation;
  context.technicalRequirementBlocksExport = (item) => context.window.TechnicalRequirementTranslation.blocksExport(item);
  context.scheduleTechnicalRequirementTranslation ||= () => {};
  context.refreshTechnicalTranslationControls ||= () => {};
}
