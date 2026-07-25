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
            const byValue = [...checked].sort((a, b) => a.value.localeCompare(b.value));

            if (isContiguous) {
                const first = byValue[0];
                const last = byValue[byValue.length - 1];
                textSpan.textContent = `${getLabel(first)} – ${getLabel(last)}`;
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

    list.addEventListener("change", function() {
        updateText();
        updateSelectAllState();
    });

    selectAll.addEventListener("change", function() {
        getCheckboxes().forEach(cb => {
            cb.checked = selectAll.checked;
        });

        updateText();
        updateSelectAllState();
    });

    document.addEventListener("click", function() {
        ms.classList.remove("open");
    });

    updateText();
    updateSelectAllState();
}