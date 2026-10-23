import fs from "node:fs";
import vm from "node:vm";

// Legacy UI tests execute isolated app function blocks, not the index.html
// script graph. Load the real shared classifier instead of stubbing it.
export function translationTestHelpers(context) {
  context.window ||= {};
  context.structuredClone ||= structuredClone;
  vm.runInContext(fs.readFileSync(new URL("../frontend/company-surface-mapping.js", import.meta.url), "utf8"), context);
  context.CompanySurfaceMapping.setCatalog(JSON.parse(fs.readFileSync(new URL("../config/company_surface_catalog.json", import.meta.url), "utf8")));
  if (!context.TechnicalRequirementEquivalence) vm.runInContext(fs.readFileSync(new URL("../frontend/technical-requirement-equivalence.js", import.meta.url), "utf8"), context);
  const app = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
  vm.runInContext(app.slice(app.indexOf("function surfaceSourceLinks"), app.indexOf("function technicalRowIds", app.indexOf("function surfaceSourceLinks"))), context);
  vm.runInContext(fs.readFileSync(new URL("../frontend/technical-requirement-translation.js", import.meta.url), "utf8"), context);
  context.technicalTranslationService = () => context.window.TechnicalRequirementTranslation;
  context.technicalRequirementBlocksExport = (item) => Boolean(context.CompanySurfaceMapping.reason(item) || context.window.TechnicalRequirementTranslation.blocksExport(item));
  context.scheduleTechnicalRequirementTranslation ||= () => {};
  context.refreshTechnicalTranslationControls ||= () => {};
}
