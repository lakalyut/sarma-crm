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

    function updateText() {
        const checked = getCheckboxes()
            .filter(cb => cb.checked)
            .map(cb => cb.value);

        if (checked.length === 0) {
            textSpan.textContent = config.emptyText || "Не выбраны";
        } else if (checked.length <= 2) {
            textSpan.textContent = checked.join(", ");
        } else {
            textSpan.textContent = checked.slice(0, 2).join(", ") + " +" + (checked.length - 2);
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