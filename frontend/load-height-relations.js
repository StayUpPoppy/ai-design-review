/* Original dimension types and deterministic load-height chains; no IO. */
(() => {
  const VERSION = "load-height/v1", units = { mm:1, "毫米":1, cm:10, "厘米":10, m:1000, "米":1000, in:25.4, inch:25.4 };
  const number = value => typeof value === "boolean" || value == null || typeof value === "object" || String(value).trim() === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const mm = (value,unit) => number(value) != null && units[String(unit || "").trim().toLowerCase()] != null ? Number((number(value)*units[String(unit).trim().toLowerCase()]).toFixed(12)) : null;
  const clone = value => value == null ? value : structuredClone(value);
  const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(key => [key,stable(value[key])])) : value;
  const same = (a,b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));
  const sameScope = (a,b) => (a.height_relation?.page ?? a.page ?? 1) === (b.height_relation?.page ?? b.page ?? 1) && (a.height_relation?.scope || "") === (b.height_relation?.scope || "");
  const snapshot = point => point.height_relation ? Object.fromEntries(["version","kind","mode","value","unit","base_point_id","reference_only","verified","last_inputs","status"].map(key => [key,clone(point.height_relation[key] ?? null)])) : null;
  function manual(point) {
    if (point.height_relation) Object.assign(point.height_relation,{mode:"manual",status:"manual",reason:"",formula:""});
    delete point.load_height_conflict;
  }
  function refresh(review) {
    if (review.drawing_summary?.spring_type && review.drawing_summary.spring_type !== "compression_spring") return [];
    const parameters = review.spring_parameters || {}, points = parameters.load_points || [], free = parameters.free_length || {};
    for (const point of points) {
      const c=point.height_calculation || {}, sources=Array.isArray(point.source) ? point.source : [point.source || ""];
      if (point.height_relation || c.formula !== "H0-deflection" || sources.some(s=>/^(human_edited|manual|human_added)/.test(s))) continue;
      const delta=mm(point.deflection,point.deflection_unit), h0=number(c.free_length), height=mm(point.height,point.height_unit);
      if (delta==null || h0==null || height==null || Math.abs(height-(h0-delta))>1e-9) continue;
      point.height_relation={version:VERSION,kind:"free_deflection",mode:"automatic",value:delta,unit:"mm",verified:true,verification_method:"structured_deflection",
        page:point.page || 1,scope:String(review.multi_spec_origin?.variant_id || ""),reference_only:Boolean(point.reference_only),evidence:point.evidence || "原规格表明确的变形量",
        last_inputs:{free_length_mm:h0,dimension_mm:delta,kind:"free_deflection",reference_only:Boolean(point.reference_only)}};
    }
    const h0 = mm(free.value,free.unit), byId = new Map(points.filter(p=>p.load_point_id).map(p=>[p.load_point_id,p]));
    const changes = [], visited = new Map(), visiting = new Set();
    function resolve(point) {
      const key = point.load_point_id || point;
      if (visited.has(key)) return visited.get(key);
      const relation = point.height_relation;
      if (!relation || relation.mode === "manual") { const value = mm(point.height,point.height_unit); return value != null && value > 0 ? value : null; }
      if (relation.preserve_existing_value && !relation.verified) { const value=mm(point.height,point.height_unit); if (value!=null && value>0) return value; }
      if (visiting.has(key)) return null;
      visiting.add(key);
      const before = clone(point), distance = mm(relation.value,relation.unit), inputs = {};
      let value = null, reason = "", formula = "";
      if (!relation.verified || relation.kind === "unknown") reason = "高度尺寸的起止关系尚未核实，请核对原图";
      else if (distance == null || distance < 0) reason = "原始高度/行程的数值或单位无效";
      else if (point.load_height_conflict) reason = "原图高度或公差证据存在冲突，请核对";
      else if (relation.kind === "absolute_height") { value = distance; formula = "H = 原图工作高度"; }
      else if (relation.kind === "free_deflection") {
        if (h0 == null || h0 <= 0) reason = "缺少有效自由高度，工作高度保持空值";
        else if (free.derived_value_stale || free.formula_recommendation_stale) reason = "自由高度已失效，请先核对";
        else { value = h0-distance; formula = "H = H0 - S"; inputs.free_length_mm = h0; }
      } else if (relation.kind === "incremental_deflection") {
        let base;
        if (relation.base_point_id) base = byId.get(relation.base_point_id);
        else {
          const matches = points.filter(p=>String(p.label || "").trim().toLowerCase() === String(relation.base_label || "").toLowerCase() && sameScope(point,p));
          if (matches.length === 1) { base = matches[0]; relation.base_point_id = base.load_point_id || ""; }
        }
        if (!base || !sameScope(point,base)) reason = "追加行程的参考载荷点未唯一确定或已删除";
        else {
          const baseHeight = resolve(base);
          if (baseHeight == null) reason = "参考载荷点高度未确定或存在循环依赖";
          else { value = baseHeight-distance; formula = "H = H参考点 - ΔS"; Object.assign(inputs,{base_point_id:base.load_point_id,base_height_mm:baseHeight,base_inputs:clone(base.height_relation?.last_inputs ?? null)}); }
        }
      }
      Object.assign(inputs,{dimension_mm:distance,kind:relation.kind,reference_only:Boolean(relation.reference_only || inputs.base_inputs?.reference_only)});
      if (value != null) {
        value = Number(value.toFixed(12));
        if (!Number.isFinite(value) || value <= 0 || relation.kind !== "absolute_height" && h0 != null && h0 > 0 && value > h0) { value = null; reason = "换算工作高度须为正数且不能超过自由高度"; }
      }
      const changed = point.height !== value || point.height_unit !== "mm" || !same(relation.last_inputs,inputs);
      point.height = value; point.height_unit = "mm";
      Object.assign(relation,{status:value != null ? "calculated" : "pending",reason,formula,last_inputs:inputs});
      if (changed) {
        point.need_human_review = true;
        if (review.manual_confirmations) { delete review.manual_confirmations[`load_point_${point.load_point_id}`]; delete review.manual_confirmations[`load_points_${points.indexOf(point)}`]; }
        changes.push({load_point_id:point.load_point_id,before,after:clone(point)});
      }
      visiting.delete(key); visited.set(key,value); return value;
    }
    points.forEach(resolve);
    for (const point of points) {
      const relation = point.height_relation, base = byId.get(relation?.base_point_id);
      const a = number(base?.force), b = number(point.force), delta = mm(relation?.value,relation?.unit);
      if (base && relation?.status === "calculated" && delta && a != null && b != null && base.force_unit === "N" && point.force_unit === "N") {
        const rate=Number(((b-a)/delta).toFixed(8));relation.secant_rate=rate;
        let warning=rate<=0 ? "行程增加但载荷未增加，请核对" : "";
        const declared=parameters.spring_rate || {}, sources=Array.isArray(declared.source) ? declared.source : [declared.source || ""];
        const k=number(declared.value), up=number(declared.tolerance_upper), down=number(declared.tolerance_lower);
        if (!sources.some(s=>/formula|derived/.test(s)) && declared.unit==="N/mm" && k!=null && up!=null && down!=null && !(k+down-1e-9<=rate && rate<=k+up+1e-9)) warning="尺寸链换算刚度与原图刚度公差不一致，请核对";
        if(warning)relation.check_warning=warning;else delete relation.check_warning;
      }
    }
    return changes;
  }
  globalThis.LoadHeightRelations = { VERSION, refresh, manual, snapshot };
})();
