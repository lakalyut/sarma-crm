// Прогрессивное улучшение нативного <select class="js-custom-select"> —
// заменяет системную выпадающую панель на свою (.custom-select-dropdown),
// сам <select> остаётся в DOM (скрыт, но участвует в отправке формы),
// value синхронизируется в обе стороны через настоящее событие "change" —
// поэтому существующие onchange="..." и JS-обработчики на select
// продолжают работать без изменений.

function initCustomSelect(select) {
    if (!select || select.dataset.customSelectReady) return;
    select.dataset.customSelectReady = "1";

    const wrapper = document.createElement("div");
    wrapper.className = "custom-select";

    select.className
        .split(/\s+/)
        .filter(function (c) { return c && c !== "js-custom-select"; })
        .forEach(function (c) { wrapper.classList.add(c); });

    // Инлайновый style на select (обычно min-width/width под конкретное
    // место в разметке) переносим на обёртку — иначе он просто теряется.
    if (select.getAttribute("style")) {
        wrapper.setAttribute("style", select.getAttribute("style"));
    }

    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    select.classList.add("custom-select-native");

    const display = document.createElement("div");
    display.className = "custom-select-display";
    display.tabIndex = 0;

    const text = document.createElement("span");
    text.className = "custom-select-text";

    const arrow = document.createElement("span");
    arrow.className = "custom-select-arrow";
    arrow.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="10" height="10"><polyline points="6 9 12 15 18 9"></polyline></svg>';

    display.appendChild(text);
    display.appendChild(arrow);

    const dropdown = document.createElement("div");
    dropdown.className = "custom-select-dropdown";

    function syncDisplay() {
        const selected = select.options[select.selectedIndex];
        text.textContent = selected ? selected.textContent.trim() : "";

        Array.from(dropdown.children).forEach(function (el) {
            el.classList.toggle("active", el.dataset.value === select.value);
        });
    }

    Array.from(select.options).forEach(function (opt) {
        const item = document.createElement("div");
        item.className = "custom-select-option";
        item.dataset.value = opt.value;
        item.textContent = opt.textContent.trim();

        item.addEventListener("click", function () {
            if (select.value !== opt.value) {
                select.value = opt.value;
                select.dispatchEvent(new Event("change", { bubbles: true }));
            }
            wrapper.classList.remove("open");
            syncDisplay();
        });

        dropdown.appendChild(item);
    });

    display.addEventListener("click", function (e) {
        e.stopPropagation();
        document.querySelectorAll(".custom-select.open").forEach(function (el) {
            if (el !== wrapper) el.classList.remove("open");
        });
        wrapper.classList.toggle("open");
    });

    display.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            wrapper.classList.toggle("open");
        } else if (e.key === "Escape") {
            wrapper.classList.remove("open");
        }
    });

    dropdown.addEventListener("click", function (e) {
        e.stopPropagation();
    });

    wrapper.appendChild(display);
    wrapper.appendChild(dropdown);

    syncDisplay();
}

function initCustomSelects(root) {
    (root || document).querySelectorAll("select.js-custom-select").forEach(initCustomSelect);
}

document.addEventListener("DOMContentLoaded", function () {
    initCustomSelects(document);

    document.addEventListener("click", function () {
        document.querySelectorAll(".custom-select.open").forEach(function (el) {
            el.classList.remove("open");
        });
    });
});
