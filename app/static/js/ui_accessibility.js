// Общие правила для серверной разметки. Нативные формы и таблицы остаются
// доступными без JavaScript; здесь дополняем интерактивные заголовки и скролл.
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("th[data-sort], th[data-sort-key], .th-filter-trigger").forEach(el => {
        if (el.dataset.keyboardReady) return;
        el.dataset.keyboardReady = "1";
        el.tabIndex = 0;
        if (el.tagName !== "TH") el.setAttribute("role", "button");
        el.addEventListener("keydown", e => {
            if (e.target !== el) return;
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.click(); }
        });
    });
    document.querySelectorAll(".sheet-scroller, .table-wrap, .empty-cities-table-wrap").forEach(el => {
        // Скролл таблицы доступен стрелками с клавиатуры.
        function updateScrollRegion() {
            if (el.scrollWidth > el.clientWidth) {
                el.tabIndex = 0;
                el.setAttribute("role", "region");
                el.setAttribute("aria-label", "Таблица — прокрутка по горизонтали");
            } else {
                el.removeAttribute("tabindex");
                el.removeAttribute("role");
                el.removeAttribute("aria-label");
            }
        }
        updateScrollRegion();
        if (window.ResizeObserver) new ResizeObserver(updateScrollRegion).observe(el);
        else window.addEventListener("resize", updateScrollRegion);
    });
});

// Подсказки поиска могут пересобираться после запроса; обработчик остаётся
// на поле ввода, а варианты выбираются через уже существующий click.
function initSuggestionKeyboard(input, dropdown) {
    if (!input || !dropdown) return;
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", dropdown.id);
    input.setAttribute("aria-expanded", "false");
    dropdown.setAttribute("role", "listbox");
    dropdown.setAttribute("aria-label", input.labels?.[0]?.textContent.trim() || input.placeholder || "Варианты поиска");
    let active = -1;
    function items() {
        return Array.from(dropdown.querySelectorAll(".search-dropdown-item, .client-list-item"))
            .filter(el => !el.classList.contains("hidden") && !el.classList.contains("is-hidden"));
    }
    function sync() {
        const open = getComputedStyle(dropdown).display !== "none";
        input.setAttribute("aria-expanded", String(open));
        dropdown.querySelectorAll(".search-dropdown-item, .client-list-item").forEach((el, i) => {
            el.id = dropdown.id + "-option-" + i;
            el.setAttribute("role", "option");
            el.setAttribute("aria-selected", "false");
            el.classList.remove("keyboard-active");
        });
        active = -1;
        input.removeAttribute("aria-activedescendant");
    }
    function close() {
        dropdown.style.display = "none";
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        active = -1;
    }
    input.addEventListener("keydown", e => {
        if (e.key === "Escape") { e.preventDefault(); close(); return; }
        if (e.key === "Tab") { close(); return; }
        if (!["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) return;
        if (e.key === "Enter") {
            if (active >= 0 && items()[active]) {
                e.preventDefault(); items()[active].click(); active = -1;
            }
            return;
        }
        e.preventDefault();
        const options = items();
        if (!options.length) return;
        dropdown.style.display = "block";
        dropdown.classList.remove("is-hidden");
        input.setAttribute("aria-expanded", "true");
        active = Math.max(0, Math.min(options.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
        options.forEach((el, i) => {
            el.classList.toggle("keyboard-active", i === active);
            el.setAttribute("aria-selected", String(i === active));
        });
        input.setAttribute("aria-activedescendant", options[active].id);
        options[active].scrollIntoView({ block: "nearest" });
    });
    input.addEventListener("input", sync);
    input.addEventListener("focus", sync);
    input.addEventListener("blur", close);
    dropdown.addEventListener("mousedown", e => {
        if (e.target.closest(".search-dropdown-item, .client-list-item")) e.preventDefault();
    });
    new MutationObserver(records => {
        if (records.some(record => record.type === "childList")) sync();
        else input.setAttribute("aria-expanded", String(getComputedStyle(dropdown).display !== "none"));
    }).observe(dropdown, { childList: true, attributes: true, attributeFilter: ["style", "class"] });
    sync();
}
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".search-dropdown[id], .client-list[id]").forEach(dropdown => {
        const field = dropdown.closest(".field, .filter-field");
        initSuggestionKeyboard(field?.querySelector('input[type="text"]'), dropdown);
    });
});
