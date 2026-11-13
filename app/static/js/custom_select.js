// Нативный select сохраняет значение формы и события change. Комбобокс
// позволяет выбирать мышью, стрелками, Home/End и поиском по первым буквам.
function initCustomSelect(select) {
    if (!select || select.dataset.customSelectReady) return;
    select.dataset.customSelectReady = "1";
    const searchable = select.hasAttribute("data-searchable");
    const wrapper = document.createElement("div");
    wrapper.className = "custom-select";
    if (searchable) wrapper.classList.add("custom-select-searchable");
    select.className.split(/\s+/).filter(c => c && c !== "js-custom-select")
        .forEach(c => wrapper.classList.add(c));
    if (select.getAttribute("style")) wrapper.setAttribute("style", select.getAttribute("style"));
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    select.classList.add("custom-select-native");

    const display = document.createElement(searchable ? "input" : "div");
    display.className = "custom-select-display";
    display.setAttribute("role", "combobox");
    display.setAttribute("aria-haspopup", "listbox");
    display.setAttribute("aria-expanded", "false");
    if (searchable) {
        display.type = "text";
        display.autocomplete = "off";
        display.setAttribute("aria-autocomplete", "list");
        display.placeholder = "Начните вводить";
    }
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
    if (!searchable) display.append(text, arrow);
    const dropdown = document.createElement("div");
    dropdown.className = "custom-select-dropdown";
    dropdown.id = "select-list-" + (++initCustomSelect.sequence);
    dropdown.setAttribute("role", "listbox");
    dropdown.setAttribute("aria-label", display.getAttribute("aria-label"));
    display.setAttribute("aria-controls", dropdown.id);
    wrapper.append(display, dropdown);
    if (searchable) wrapper.append(arrow);
    let activeIndex = select.selectedIndex;
    let query = "", queryTime = 0;
    const enabled = opt => !opt.disabled && !(opt.parentElement.tagName === "OPTGROUP" && opt.parentElement.disabled);

    const viewport = window.visualViewport;
    const usesPopover = typeof dropdown.showPopover === "function";
    if (usesPopover) dropdown.popover = "manual";

    function positionDropdown() {
        if (!wrapper.classList.contains("open") || !display.getClientRects().length) return;
        const rect = display.getBoundingClientRect();
        const gap = 6;
        const edge = 8;
        const top = viewport?.offsetTop ?? 0;
        const left = viewport?.offsetLeft ?? 0;
        const bottom = top + (viewport?.height ?? window.innerHeight);
        const right = left + (viewport?.width ?? window.innerWidth);
        const below = Math.max(0, bottom - rect.bottom - gap - edge);
        const above = Math.max(0, rect.top - top - gap - edge);
        const desiredHeight = Math.min(260, dropdown.scrollHeight + 2);
        const opensUp = below < desiredHeight && above > below;

        dropdown.style.maxHeight = Math.min(260, opensUp ? above : below) + "px";
        wrapper.classList.toggle("opens-up", opensUp);
        if (usesPopover) {
            const cssMinWidth = getComputedStyle(dropdown).minWidth;
            const minWidth = cssMinWidth.endsWith("px") ? parseFloat(cssMinWidth) : 0;
            const width = Math.min(Math.max(rect.width, minWidth), right - left - edge * 2);
            dropdown.style.width = width + "px";
            dropdown.style.left = Math.max(left + edge, Math.min(rect.left, right - edge - width)) + "px";
            dropdown.style.top = (opensUp ? rect.top - gap - dropdown.offsetHeight : rect.bottom + gap) + "px";
        }
    }

    function filterOptions() {
        let count = 0;
        Array.from(select.options).forEach((opt, i) => {
            const visible = !query || opt.textContent.toLocaleLowerCase().includes(query);
            dropdown.children[i].hidden = !visible;
            if (visible && enabled(opt)) count++;
        });
        const empty = dropdown.querySelector(".custom-select-empty");
        if (empty) empty.hidden = count > 0;
        positionDropdown();
    }

    function highlight(index) {
        activeIndex = index;
        Array.from(dropdown.children).forEach((item, i) => item.classList.toggle("highlighted", i === index));
        const item = dropdown.children[index];
        if (index >= 0 && item && wrapper.classList.contains("open")) {
            display.setAttribute("aria-activedescendant", item.id);
            const optionRect = item.getBoundingClientRect();
            const menuRect = dropdown.getBoundingClientRect();
            if (optionRect.top < menuRect.top) dropdown.scrollTop -= menuRect.top - optionRect.top;
            else if (optionRect.bottom > menuRect.bottom) dropdown.scrollTop += optionRect.bottom - menuRect.bottom;
        } else display.removeAttribute("aria-activedescendant");
    }
    function close() {
        query = "";
        wrapper.classList.remove("open", "opens-up");
        if (usesPopover) dropdown.hidePopover();
        window.removeEventListener("scroll", positionDropdown, true);
        window.removeEventListener("resize", positionDropdown);
        viewport?.removeEventListener("resize", positionDropdown);
        viewport?.removeEventListener("scroll", positionDropdown);
        display.setAttribute("aria-expanded", "false");
        display.removeAttribute("aria-activedescendant");
        if (searchable) {
            display.value = select.selectedOptions[0]?.textContent.trim() || "";
            filterOptions();
        }
    }
    wrapper.closeCustomSelect = close;
    function open() {
        if (select.disabled) return;
        document.querySelectorAll(".custom-select.open").forEach(el => {
            if (el !== wrapper && el.closeCustomSelect) el.closeCustomSelect();
        });
        wrapper.classList.add("open");
        if (usesPopover) dropdown.showPopover();
        positionDropdown();
        window.addEventListener("scroll", positionDropdown, true);
        window.addEventListener("resize", positionDropdown);
        viewport?.addEventListener("resize", positionDropdown);
        viewport?.addEventListener("scroll", positionDropdown);
        display.setAttribute("aria-expanded", "true");
        highlight(select.selectedIndex);
    }
    function syncDisplay() {
        text.textContent = select.selectedOptions[0]?.textContent.trim() || "";
        if (searchable && !query) display.value = text.textContent;
        if (searchable) display.disabled = select.disabled;
        display.tabIndex = select.disabled ? -1 : 0;
        display.setAttribute("aria-disabled", String(select.disabled));
        display.setAttribute("aria-required", String(select.required));
        display.setAttribute("aria-invalid", select.getAttribute("aria-invalid") || "false");
        Array.from(dropdown.querySelectorAll(".custom-select-option")).forEach((item, i) => {
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
        if (searchable) {
            const empty = document.createElement("div");
            empty.className = "custom-select-empty";
            empty.textContent = "Ничего не найдено";
            empty.hidden = true;
            dropdown.appendChild(empty);
            filterOptions();
        }
        syncDisplay();
        if (wrapper.classList.contains("open")) highlight(select.selectedIndex);
    }
    display.addEventListener("click", e => {
        e.stopPropagation();
        if (searchable) { if (!wrapper.classList.contains("open")) open(); display.select(); return; }
        if (wrapper.classList.contains("open")) close(); else open();
    });
    if (searchable) display.addEventListener("input", () => {
        if (!wrapper.classList.contains("open")) open();
        query = display.value.trim().toLocaleLowerCase();
        filterOptions();
        const index = Array.from(select.options).findIndex((opt, i) => enabled(opt) && !dropdown.children[i].hidden);
        highlight(index);
    });
    if (searchable) display.addEventListener("focus", () => display.select());
    display.addEventListener("keydown", e => {
        const isOpen = wrapper.classList.contains("open");
        if (e.key === "Escape" || e.key === "Tab") { close(); return; }
        if (e.key === "Enter" || (!searchable && e.key === " " && !query)) {
            e.preventDefault();
            if (isOpen) choose(activeIndex); else open();
            return;
        }
        const options = Array.from(select.options);
        const indices = options.map((opt, i) => enabled(opt) && !dropdown.children[i].hidden ? i : -1).filter(i => i >= 0);
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
            e.preventDefault();
            if (!isOpen) open();
            let pos = indices.indexOf(activeIndex);
            if (e.key === "Home") pos = 0;
            else if (e.key === "End") pos = indices.length - 1;
            else pos = Math.max(0, Math.min(indices.length - 1, pos + (e.key === "ArrowDown" ? 1 : -1)));
            if (indices[pos] !== undefined) highlight(indices[pos]);
        } else if (!searchable && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
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
