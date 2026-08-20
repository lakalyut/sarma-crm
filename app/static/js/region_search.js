// Поиск-с-подсказками "Регион"/"Город" на single-select страницах аналитики
// (Клиенты, Графики) — при выборе города переходит на страницу с ним, заодно
// восстанавливая вложенные фильтры (месяцы/типы/сопоставлено) из localStorage
// для этого конкретного города. Не путать с многотегным initTagSearch
// (tag_search.js, для мультивыбора клиентов/SKU) или запоминанием самого
// последнего региона между страницами (region_memory.js) — это разные,
// сознательно не объединённые задачи (см. CLAUDE.md).

function filterSearchDropdown(input, items, dropdown) {
    const value = input.value.trim().toLowerCase();
    let visibleCount = 0;

    items.forEach(item => {
        const text = item.dataset.value.toLowerCase();
        const visible = !value || text.includes(value);
        item.classList.toggle("hidden", !visible);
        if (visible) visibleCount++;
    });

    dropdown.style.display = visibleCount > 0 ? "block" : "none";
    return visibleCount;
}

// Сохраняет отмеченные месяцы/типы/сопоставлено при сабмите формы фильтров
// под ключом storagePrefix+город — читается buildRegionUrlWithFilters при
// следующем выборе того же города.
function initFilterMemory(config) {
    const form = document.getElementById(config.formId);
    if (!form) return;

    const cityInput = document.getElementById(config.cityHiddenId);
    const currentCity = cityInput && cityInput.value;
    if (!currentCity) return;

    const storageKey = config.storagePrefix + currentCity;

    form.addEventListener("submit", function () {
        const months = Array.from(form.querySelectorAll('input[name="months"]:checked')).map(i => i.value);
        const types = Array.from(form.querySelectorAll('input[name="sale_types"]:checked')).map(i => i.value);
        const matched = (form.querySelector('select[name="matched"]') || {}).value || "";

        const state = { months, types, matched };

        try {
            localStorage.setItem(storageKey, JSON.stringify(state));
        } catch (e) {
            console.warn("Не удалось сохранить фильтры:", e);
        }
    });
}

function buildRegionUrlWithFilters(path, cityValue, storagePrefix) {
    const url = new URL(window.location.origin + path);
    url.searchParams.set("city", cityValue);

    const storageKey = storagePrefix + cityValue;

    try {
        const raw = localStorage.getItem(storageKey);
        if (raw) {
            const saved = JSON.parse(raw);

            if (Array.isArray(saved.months)) {
                saved.months.forEach(m => url.searchParams.append("months", m));
            }

            if (Array.isArray(saved.types)) {
                saved.types.forEach(t => url.searchParams.append("sale_types", t));
            }

            if (saved.matched !== undefined && saved.matched !== null && saved.matched !== "") {
                url.searchParams.set("matched", saved.matched);
            }
        }
    } catch (e) {
        console.warn("Не удалось восстановить фильтры региона:", cityValue, e);
    }

    return url.toString();
}

function initRegionSearch(config) {
    const input = document.getElementById(config.inputId);
    const hidden = document.getElementById(config.hiddenId);
    const dropdown = document.getElementById(config.dropdownId);
    const selectedCityLabel = config.labelId ? document.getElementById(config.labelId) : null;
    const selectedCityEmpty = config.emptyId ? document.getElementById(config.emptyId) : null;

    if (!input || !hidden || !dropdown) return;

    const items = Array.from(dropdown.querySelectorAll(".search-dropdown-item"));

    function filterItems() {
        filterSearchDropdown(input, items, dropdown);
    }

    function buildUrl(cityValue) {
        return buildRegionUrlWithFilters(config.path, cityValue, config.storagePrefix);
    }

    if (!hidden.value) {
        const lastRegion = window.PulseRegionMemory && window.PulseRegionMemory.get();
        if (lastRegion) {
            window.location.replace(buildUrl(lastRegion));
            return;
        }
    }

    input.addEventListener("focus", filterItems);
    input.addEventListener("input", filterItems);

    items.forEach(item => {
        item.addEventListener("click", function () {
            const value = item.dataset.value;

            hidden.value = value;

            if (selectedCityLabel) {
                selectedCityLabel.textContent = value;
                selectedCityLabel.style.display = "";
            }

            if (selectedCityEmpty) {
                selectedCityEmpty.style.display = "none";
            }

            input.value = "";
            dropdown.style.display = "none";

            if (window.PulseRegionMemory) window.PulseRegionMemory.save(value);
            window.location.href = buildUrl(value);
        });
    });

    input.addEventListener("blur", function () {
        setTimeout(() => {
            input.value = "";
            dropdown.style.display = "none";
        }, 150);
    });

    document.addEventListener("click", function (e) {
        if (!dropdown.contains(e.target) && e.target !== input) {
            dropdown.style.display = "none";
        }
    });
}
