/* Search is presentation-only. The existing select owns parameter edits. */
(() => {
  const bindings = new WeakMap();
  let active = null, serial = 0;
  const key = value => String(value ?? "").normalize("NFKC").toUpperCase().replace(/[\s\-‐‑‒–—_]+/g, "");
  const visible = element => element?.isConnected && element.getClientRects().length > 0;

  function sync(select, items) {
    const binding = bindings.get(select);
    if (!binding) return;
    if (items) binding.items = items;
    const label = select.value || "请选择材料";
    binding.trigger.querySelector("[data-material-label]").textContent = label;
    binding.trigger.title = select.title || label;
    binding.trigger.disabled = select.disabled;
    binding.trigger.setAttribute("aria-label", `${select.getAttribute("aria-label") || "材料"}：${label}`);
    if (active?.binding === binding) close();
  }

  function close(restoreFocus = false) {
    if (!active) return;
    const current = active;
    active = null;
    current.observer.disconnect();
    current.panel.remove();
    current.binding.trigger.setAttribute("aria-expanded", "false");
    current.binding.trigger.removeAttribute("aria-controls");
    if (restoreFocus && visible(current.binding.trigger)) current.binding.trigger.focus({ preventScroll: true });
  }

  function current() {
    if (!active) return false;
    if (!visible(active.binding.trigger) || active.binding.select.disabled || !active.binding.isCurrent()) {
      close();
      return false;
    }
    return true;
  }

  function position() {
    if (!current()) return;
    const { panel, list, binding } = active;
    const anchor = binding.trigger.getBoundingClientRect(), viewport = window.visualViewport;
    for (let parent = binding.trigger.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      const style = getComputedStyle(parent), bounds = parent.getBoundingClientRect();
      if (/auto|scroll|hidden|clip/.test(style.overflowY) && (anchor.bottom <= bounds.top || anchor.top >= bounds.bottom)) {
        close(); return;
      }
    }
    const leftEdge = viewport?.offsetLeft || 0, topEdge = viewport?.offsetTop || 0;
    const width = viewport?.width || window.innerWidth, height = viewport?.height || window.innerHeight;
    if (anchor.bottom < topEdge || anchor.top > topEdge + height) { close(); return; }
    panel.style.width = `${Math.min(Math.max(anchor.width, 280), width - 16)}px`;
    const below = topEdge + height - anchor.bottom - 12, above = anchor.top - topEdge - 12;
    const opensUp = below < 240 && above > below;
    const available = Math.max(72, opensUp ? above : below);
    panel.style.maxHeight = `${available}px`;
    list.style.maxHeight = `${Math.max(28, Math.min(280, available - 54))}px`;
    const panelHeight = panel.getBoundingClientRect().height;
    panel.style.left = `${Math.max(leftEdge + 8, Math.min(anchor.left, leftEdge + width - panel.offsetWidth - 8))}px`;
    panel.style.top = `${opensUp ? anchor.top - panelHeight - 4 : anchor.bottom + 4}px`;
  }

  function highlight(index, scroll = true) {
    if (!current()) return;
    active.index = index;
    const options = [...active.list.children].filter(item => item.getAttribute("role") === "option");
    options.forEach((option, i) => option.classList.toggle("is-active", i === index));
    const option = options[index];
    if (option) {
      active.search.setAttribute("aria-activedescendant", option.id);
      if (scroll) option.scrollIntoView({ block: "nearest" });
    } else active.search.removeAttribute("aria-activedescendant");
  }

  function filter() {
    if (!current()) return;
    const { search, list, binding } = active, query = key(search.value);
    active.results = [...binding.select.options].filter(option => !option.disabled && (!option.value || binding.items.some(item => item.display_name === option.value)))
      .filter(option => {
        const item = binding.items.find(entry => entry.display_name === option.value);
        return !query || item && [item.display_name, item.standard_value, ...(item.aliases || [])].some(value => key(value).includes(query));
      });
    list.replaceChildren();
    for (const [index, option] of active.results.entries()) {
      const node = document.createElement("div");
      node.id = `${list.id}-${index}`;
      node.className = "material-picker-option";
      node.setAttribute("role", "option");
      node.setAttribute("aria-selected", String(option.value === binding.select.value));
      node.dataset.index = String(index);
      node.textContent = option.textContent;
      list.appendChild(node);
    }
    if (!active.results.length) {
      const empty = document.createElement("div");
      empty.className = "material-picker-empty";
      empty.setAttribute("role", "status");
      empty.textContent = "未找到匹配材料";
      list.appendChild(empty);
    }
    const selectedIndex = active.results.findIndex(option => option.value === binding.select.value);
    position();
    highlight(selectedIndex >= 0 ? selectedIndex : active.results.length ? 0 : -1);
  }

  function choose(index) {
    if (!current()) return;
    const { binding, results } = active, option = results[index];
    if (!option) return;
    const value = option.value;
    close(true);
    if (binding.select.value === value || !binding.isCurrent()) return;
    binding.select.value = value;
    binding.select.dispatchEvent(new Event("input", { bubbles: true }));
    binding.select.dispatchEvent(new Event("change", { bubbles: true }));
    sync(binding.select);
  }

  function open(binding) {
    if (binding.select.disabled || !binding.isCurrent()) return;
    if (active?.binding === binding) { close(true); return; }
    close();
    const panel = document.createElement("div"), search = document.createElement("input"), list = document.createElement("div");
    panel.className = "material-picker-panel";
    panel.id = `material-picker-${++serial}`;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "选择材料");
    search.className = "material-picker-search";
    search.type = "search";
    search.placeholder = "搜索材料名称、牌号或别名";
    search.setAttribute("aria-label", search.placeholder);
    search.setAttribute("role", "combobox");
    search.setAttribute("aria-autocomplete", "list");
    search.setAttribute("aria-expanded", "true");
    search.autocomplete = "off";
    list.className = "material-picker-list";
    list.id = `${panel.id}-list`;
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "材料选项");
    search.setAttribute("aria-controls", list.id);
    const header = document.createElement("div");
    header.className = "material-picker-search-header";
    header.appendChild(search);
    panel.append(header, list);
    document.body.appendChild(panel);
    const observer = new MutationObserver(() => { current(); });
    active = { binding, panel, search, list, observer, results: [], index: -1, composing: false };
    observer.observe(document.body, { childList: true, subtree: true });
    binding.trigger.setAttribute("aria-expanded", "true");
    binding.trigger.setAttribute("aria-controls", panel.id);
    search.addEventListener("input", () => { if (active?.search === search) filter(); });
    search.addEventListener("compositionstart", () => { if (active?.search === search) active.composing = true; });
    search.addEventListener("compositionend", () => { if (active?.search === search) active.composing = false; });
    search.addEventListener("keydown", event => {
      if (active?.panel !== panel || !current() || event.isComposing || active.composing || event.keyCode === 229) return;
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        highlight(active.results.length ? (active.index + delta + active.results.length) % active.results.length : -1);
      } else if (event.key === "Enter") {
        event.preventDefault(); choose(active.index);
      } else if (event.key === "Escape") {
        event.preventDefault(); event.stopPropagation(); close(true);
      } else if (event.key === "Tab") {
        event.preventDefault();
        const controls = [...document.querySelectorAll('button, input, select, textarea, a[href], [tabindex]')]
          .filter(element => element.tabIndex >= 0 && !element.disabled && visible(element) && !panel.contains(element));
        const next = controls[controls.indexOf(binding.trigger) + (event.shiftKey ? -1 : 1)];
        close();
        (next || binding.trigger).focus({ preventScroll: true });
      }
    });
    list.addEventListener("pointerdown", event => event.preventDefault());
    list.addEventListener("click", event => {
      if (active?.panel !== panel) return;
      const option = event.target.closest('[role="option"]');
      if (option) choose(Number(option.dataset.index));
    });
    list.addEventListener("pointermove", event => {
      if (active?.panel !== panel) return;
      const option = event.target.closest('[role="option"]');
      if (option && Number(option.dataset.index) !== active?.index) highlight(Number(option.dataset.index), false);
    });
    filter();
    search.focus({ preventScroll: true });
  }

  function bind(select, { items, isCurrent }) {
    const trigger = select.parentElement.querySelector("[data-material-trigger]");
    if (!trigger) return;
    let binding = bindings.get(select);
    if (!binding) {
      binding = { select, trigger, items, isCurrent };
      bindings.set(select, binding);
      trigger.addEventListener("click", () => open(binding));
      trigger.addEventListener("keydown", event => {
        if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); open(binding); }
      });
    }
    binding.isCurrent = isCurrent;
    sync(select, items);
  }

  document.addEventListener("pointerdown", event => {
    if (active && !active.panel.contains(event.target) && !active.binding.trigger.contains(event.target)) close();
  }, true);
  document.addEventListener("focusin", event => {
    if (active && !active.panel.contains(event.target) && event.target !== active.binding.trigger) close();
  });
  window.addEventListener("resize", position);
  document.addEventListener("scroll", event => {
    if (active && !active.panel.contains(event.target)) position();
  }, true);
  window.visualViewport?.addEventListener("resize", position);
  window.visualViewport?.addEventListener("scroll", position);
  globalThis.MaterialPicker = { bind, sync, close, key };
})();
