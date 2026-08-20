function initCheckboxMultiselect(config) {
    const ms = document.getElementById(config.id);
    if (!ms) return;

    const display = ms.querySelector(".multiselect-display");
    const dropdown = ms.querySelector(".multiselect-dropdown");
    const textSpan = ms.querySelector(".multiselect-text");
    const list = ms.querySelector(".month-checkboxes");
    const selectAll = ms.querySelector(".multiselect-select-all-checkbox");

    if (!display || !dropdown || !textSpan || !list || !selectAll) return;

    function getCheckboxes() {
        return Array.from(
            list.querySelectorAll(`input[type="checkbox"][name="${config.inputName}"]`)
        );
    }

    function getLabel(cb) {
        if (cb.dataset.label) return cb.dataset.label;
        const span = cb.parentElement && cb.parentElement.querySelector("span");
        return span ? span.textContent.trim() : cb.value;
    }

    // Список отсортирован сервером хронологически (обычно от новых к старым) —
    // соседние по DOM чекбоксы формируют непрерывный диапазон месяцев без
    // разбора самих дат, просто по позиции в списке.
    function updateText() {
        const all = getCheckboxes();
        const checked = all.filter(cb => cb.checked);

        if (checked.length === 0) {
            textSpan.textContent = config.emptyText || "Не выбраны";
            return;
        }

        if (config.dateRange && checked.length > 1) {
            const indices = checked.map(cb => all.indexOf(cb)).sort((a, b) => a - b);
            const isContiguous = indices[indices.length - 1] - indices[0] === indices.length - 1;
            // Значение чекбокса не всегда ISO-дата (часть городов грузится сразу
            // как "Месяц Год" — см. app/utils/dates.py:parse_month) — сортировка
            // по localeCompare(value) для таких строк не хронологическая. DOM-
            // порядок уже хронологический (сервер сортирует reverse=True), просто
            // разворачиваем его, а не пересортировываем по значению.
            const byValue = [...checked].sort((a, b) => all.indexOf(b) - all.indexOf(a));

            if (checked.length > 3) {
                if (isContiguous) {
                    const first = byValue[0];
                    const last = byValue[byValue.length - 1];
                    textSpan.textContent = `${getLabel(first)} – ${getLabel(last)}`;
                } else {
                    const labels = byValue.map(getLabel);
                    textSpan.textContent = labels.slice(0, 3).join(", ") + " +" + (labels.length - 3);
                }
            } else {
                textSpan.textContent = byValue.map(getLabel).join(", ");
            }
            return;
        }

        const labels = checked.map(getLabel);
        if (labels.length <= 2) {
            textSpan.textContent = labels.join(", ");
        } else {
            textSpan.textContent = labels.slice(0, 2).join(", ") + " +" + (labels.length - 2);
        }
    }

    function updateSelectAllState() {
        const checkboxes = getCheckboxes();
        const checked = checkboxes.filter(cb => cb.checked);

        selectAll.checked = checkboxes.length > 0 && checked.length === checkboxes.length;
        selectAll.indeterminate = checked.length > 0 && checked.length < checkboxes.length;
    }

    display.addEventListener("click", function(e) {
        e.preventDefault();
        e.stopPropagation();
        ms.classList.toggle("open");
    });

    dropdown.addEventListener("click", function(e) {
        e.stopPropagation();
    });

    let updatePager = function () {};

    list.addEventListener("change", function() {
        updateText();
        updateSelectAllState();
        updatePager();
    });

    selectAll.addEventListener("change", function() {
        getCheckboxes().forEach(cb => {
            cb.checked = selectAll.checked;
        });

        updateText();
        updateSelectAllState();
        updatePager();
    });

    document.addEventListener("click", function() {
        ms.classList.remove("open");
    });

    const pager = list.querySelector(".mp-pager");
    if (pager) {
        const yearGrids = Array.from(pager.querySelectorAll(".mp-year-grid"));
        const yearLabel = pager.querySelector(".mp-year-label");
        const prevBtn = pager.querySelector(".mp-prev");
        const nextBtn = pager.querySelector(".mp-next");
        let currentIndex = 0;

        function gridHasSelection(grid) {
            return grid.querySelector('input[type="checkbox"]:checked') !== null;
        }

        function renderPager() {
            yearGrids.forEach((grid, i) => {
                grid.classList.toggle("is-hidden", i !== currentIndex);
            });

            const current = yearGrids[currentIndex];
            const count = current.querySelectorAll('input[type="checkbox"]:checked').length;
            yearLabel.textContent = current.dataset.year + (count ? " · " + count : "");

            const atNewest = currentIndex === 0;
            const atOldest = currentIndex === yearGrids.length - 1;

            prevBtn.style.visibility = atOldest ? "hidden" : "visible";
            nextBtn.style.visibility = atNewest ? "hidden" : "visible";

            prevBtn.classList.toggle(
                "has-dot",
                !atOldest && yearGrids.slice(currentIndex + 1).some(gridHasSelection)
            );
            nextBtn.classList.toggle(
                "has-dot",
                !atNewest && yearGrids.slice(0, currentIndex).some(gridHasSelection)
            );
        }

        prevBtn.addEventListener("click", function () {
            if (currentIndex < yearGrids.length - 1) {
                currentIndex += 1;
                renderPager();
            }
        });

        nextBtn.addEventListener("click", function () {
            if (currentIndex > 0) {
                currentIndex -= 1;
                renderPager();
            }
        });

        updatePager = renderPager;
        renderPager();
    }

    // Динамическая пересборка списка чекбоксов — для страниц, где список
    // подгружается по AJAX после выбора другого фильтра (например, месяцы
    // и типы по городу на «Удалении импорта»). Только для плоских списков
    // без пейджера по годам (у пейджера чекбоксы вложены в .mp-year-grid
    // внутри этого же list — setItems их тоже стёр бы).
    function setItems(items) {
        list.innerHTML = "";

        items.forEach(item => {
            const value = typeof item === "string" ? item : item.value;
            const itemLabel = typeof item === "string" ? item : item.label;

            const label = document.createElement("label");
            label.className = "month-checkbox";

            const input = document.createElement("input");
            input.type = "checkbox";
            input.name = config.inputName;
            input.value = value;

            const span = document.createElement("span");
            span.textContent = itemLabel;

            label.appendChild(input);
            label.appendChild(span);
            list.appendChild(label);
        });

        updateText();
        updateSelectAllState();
        updatePager();
    }

    updateText();
    updateSelectAllState();

    return { setItems };
}