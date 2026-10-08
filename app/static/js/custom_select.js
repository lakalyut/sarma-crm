// Нативный select сохраняет значение формы и события change. Комбобокс
// позволяет выбирать мышью, стрелками, Home/End и поиском по первым буквам.
function initCustomSelect(select) {
    if (!select || select.dataset.customSelectReady) return;
    select.dataset.customSelectReady = "1";
    const wrapper = document.createElement("div");
    wrapper.className = "custom-select";
    select.className.split(/\s+/).filter(c => c && c !== "js-custom-select")
        .forEach(c => wrapper.classList.add(c));
    if (select.getAttribute("style")) wrapper.setAttribute("style", select.getAttribute("style"));
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    select.classList.add("custom-select-native");

    const display = document.createElement("div");
    display.className = "custom-select-display";
    display.setAttribute("role", "combobox");
    display.setAttribute("aria-haspopup", "listbox");
    display.setAttribute("aria-expanded", "false");
    const label = (select.labels && select.labels[0]) ||
        wrapper.parentElement.querySelector("label");
    display.setAttribute("aria-label", select.getAttribute("aria-label") ||
        (label && label.textContent.trim()) || select.name || "Выбор значения");
    const text = document.createElement("span");
    text.className = "custom-select-text";
    const arrow = document.createElement("span");
    arrow.className = "custom-select-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="10" height="10"><polyline points="6 9 12 15 18 9"></polyline></svg>';
    display.append(text, arrow);
    const dropdown = document.createElement("div");
    dropdown.className = "custom-select-dropdown";
    dropdown.id = "select-list-" + (++initCustomSelect.sequence);
    dropdown.setAttribute("role", "listbox");
    dropdown.setAttribute("aria-label", display.getAttribute("aria-label"));
    display.setAttribute("aria-controls", dropdown.id);
    wrapper.append(display, dropdown);
    let activeIndex = select.selectedIndex;
    let query = "", queryTime = 0;
    const enabled = opt => !opt.disabled && !(opt.parentElement.tagName === "OPTGROUP" && opt.parentElement.disabled);

    function highlight(index) {
        activeIndex = index;
        Array.from(dropdown.children).forEach((item, i) => item.classList.toggle("highlighted", i === index));
        const item = dropdown.children[index];
        if (item && wrapper.classList.contains("open")) {
            display.setAttribute("aria-activedescendant", item.id);
            item.scrollIntoView({ block: "nearest" });
        }
    }
    function close() {
        query = "";
        wrapper.classList.remove("open");
        display.setAttribute("aria-expanded", "false");
        display.removeAttribute("aria-activedescendant");
    }
    wrapper.closeCustomSelect = close;
    function open() {
        if (select.disabled) return;
        document.querySelectorAll(".custom-select.open").forEach(el => {
            if (el !== wrapper && el.closeCustomSelect) el.closeCustomSelect();
        });
        wrapper.classList.add("open");
        display.setAttribute("aria-expanded", "true");
        highlight(select.selectedIndex);
    }
    function syncDisplay() {
        text.textContent = select.selectedOptions[0]?.textContent.trim() || "";
        display.tabIndex = select.disabled ? -1 : 0;
        display.setAttribute("aria-disabled", String(select.disabled));
        display.setAttribute("aria-required", String(select.required));
        display.setAttribute("aria-invalid", select.getAttribute("aria-invalid") || "false");
        Array.from(dropdown.children).forEach((item, i) => {
            item.classList.toggle("active", i === select.selectedIndex);
            item.setAttribute("aria-selected", String(i === select.selectedIndex));
        });
        if (select.disabled) close();
    }
    function choose(index) {
        const option = select.options[index];
        if (!option || !enabled(option) || select.disabled) return;
        const changed = select.selectedIndex !== index;
        select.selectedIndex = index;
        close();
        syncDisplay();
        display.focus();
        if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    function rebuild() {
        dropdown.replaceChildren();
        Array.from(select.options).forEach((opt, i) => {
            const item = document.createElement("div");
            item.className = "custom-select-option";
            item.id = dropdown.id + "-" + i;
            item.dataset.value = opt.value;
            item.textContent = opt.textContent.trim();
            item.setAttribute("role", "option");
            item.setAttribute("aria-disabled", String(!enabled(opt)));
            item.addEventListener("click", () => choose(i));
            dropdown.appendChild(item);
        });
        syncDisplay();
        if (wrapper.classList.contains("open")) highlight(select.selectedIndex);
    }
    display.addEventListener("click", e => {
        e.stopPropagation();
        if (wrapper.classList.contains("open")) close(); else open();
    });
    display.addEventListener("keydown", e => {
        const isOpen = wrapper.classList.contains("open");
        if (e.key === "Escape" || e.key === "Tab") { close(); return; }
        if (e.key === "Enter" || (e.key === " " && !query)) {
            e.preventDefault();
            if (isOpen) choose(activeIndex); else open();
            return;
        }
        const options = Array.from(select.options);
        const indices = options.map((opt, i) => enabled(opt) ? i : -1).filter(i => i >= 0);
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
            e.preventDefault();
            if (!isOpen) open();
            let pos = indices.indexOf(activeIndex);
            if (e.key === "Home") pos = 0;
            else if (e.key === "End") pos = indices.length - 1;
            else pos = Math.max(0, Math.min(indices.length - 1, pos + (e.key === "ArrowDown" ? 1 : -1)));
            if (indices[pos] !== undefined) highlight(indices[pos]);
        } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            const now = Date.now();
            query = (now - queryTime > 700 ? "" : query) + e.key.toLocaleLowerCase();
            queryTime = now;
            const index = indices.find(i => options[i].textContent.trim().toLocaleLowerCase().startsWith(query));
            if (index !== undefined) { if (!isOpen) open(); highlight(index); }
        }
    });
    wrapper.addEventListener("focusout", e => { if (!wrapper.contains(e.relatedTarget)) close(); });
    // Пункт — нефокусируемый div. Его mousedown иначе переводит фокус
    // на body, focusout закрывает меню раньше click и выбор теряется.
    // Не перехватываем pointerdown/touchstart: прокрутка касанием остаётся нативной.
    dropdown.addEventListener("mousedown", e => {
        if (e.target.closest(".custom-select-option")) e.preventDefault();
    });
    dropdown.addEventListener("click", e => e.stopPropagation());
    select.addEventListener("change", syncDisplay);
    select.addEventListener("display-sync", syncDisplay);
    if (label) label.addEventListener("click", () => display.focus());
    new MutationObserver(rebuild).observe(select, { childList: true, subtree: true, attributes: true });
    rebuild();
}
initCustomSelect.sequence = 0;
function initCustomSelects(root) {
    (root || document).querySelectorAll("select.js-custom-select").forEach(initCustomSelect);
}
document.addEventListener("DOMContentLoaded", () => {
    initCustomSelects(document);
    document.addEventListener("click", () => document.querySelectorAll(".custom-select.open")
        .forEach(el => el.closeCustomSelect && el.closeCustomSelect()));
});
