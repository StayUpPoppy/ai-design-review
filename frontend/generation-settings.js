/* Drawing presentation options, separate from spring parameters and login identity. */
globalThis.GenerationSettings = (() => {
  function values(review, identity = {}) {
    const settings = review?.generation_settings || {};
    return { drawing_model: settings.drawing_model ?? "X型",
      username: Object.hasOwn(settings, "username") ? settings.username : String(identity?.real_name || identity?.username || "").trim() };
  }
  function error(settings) {
    if (!["X型", "Y型"].includes(settings?.drawing_model)) return "请选择横版或竖版。";
    if (typeof settings.username !== "string" || !settings.username.trim()) return "请填写生图人姓名。";
    if (Array.from(settings.username.trim()).length > 256) return "生图人姓名不能超过256个字符。";
    return "";
  }
  function normalized(settings) {
    const message = error(settings);
    if (message) throw new Error(message);
    return { drawing_model: settings.drawing_model, username: settings.username.trim() };
  }
  return { values, error, normalized };
})();
