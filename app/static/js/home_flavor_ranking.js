function initHomeFlavorRanking(lineFilter, list, expandable) {
    const lineButtons = [...lineFilter.querySelectorAll("[data-line]")];
    const allButton = document.getElementById("home-flavors-all");
    const cityButton = document.getElementById("home-flavors-city");
    const cityField = document.getElementById("home-flavor-city-field");
    const citySelect = document.getElementById("home-flavor-city");
    const message = document.getElementById("home-flavors-message");
    const overallRows = [...list.children];
    let selectedLine = "__all__";
    let byCity = false;
    let request;

    function showMessage(text) {
        message.textContent = text;
        message.hidden = !text;
    }

    function applyFilter() {
        const showAll = selectedLine === "__all__";
        for (const row of list.children) {
            row.classList.toggle("is-filtered-out", !showAll && row.dataset.line !== selectedLine);
            const overall = row.querySelector(".js-abc-overall");
            const lineBadge = row.querySelector(".js-abc-line");
            if (overall) overall.hidden = !showAll;
            if (lineBadge) lineBadge.hidden = showAll;
        }
        expandable.refresh();
    }

    function showResults() {
        applyFilter();
        const visible = [...list.children].some(row => !row.hidden);
        showMessage(visible ? "" : "За выбранный период нет продаж вкусов для этого фильтра.");
    }

    lineButtons.forEach(button => {
        button.addEventListener("click", () => {
            selectedLine = button.dataset.line;
            lineButtons.forEach(item => {
                item.classList.toggle("active", item === button);
                item.setAttribute("aria-pressed", String(item === button));
            });
            if (list.children.length || message.hidden) showResults();
        });
    });

    if (!citySelect) return;

    async function updateScope() {
        request?.abort();
        cityField.hidden = !byCity;
        allButton.classList.toggle("active", !byCity);
        cityButton.classList.toggle("active", byCity);
        allButton.setAttribute("aria-pressed", String(!byCity));
        cityButton.setAttribute("aria-pressed", String(byCity));

        if (!byCity) {
            list.replaceChildren(...overallRows);
            showResults();
            return;
        }

        list.replaceChildren();
        expandable.refresh();
        if (!citySelect.value) {
            showMessage("Выберите город.");
            return;
        }

        const controller = new AbortController();
        request = controller;
        const params = new URLSearchParams({city: citySelect.value, year: list.dataset.year});
        showMessage("Загружаем рейтинг…");
        try {
            const response = await fetch("/analytics/city-flavor-abc?" + params, {
                signal: controller.signal,
            });
            if (!response.ok || response.redirected) throw new Error("Не удалось загрузить рейтинг");
            const html = await response.text();
            if (controller.signal.aborted) return;
            list.innerHTML = html;
            showResults();
        } catch {
            if (!controller.signal.aborted) showMessage("Не удалось загрузить рейтинг. Выберите город снова.");
        }
    }

    allButton.addEventListener("click", () => {
        byCity = false;
        updateScope();
    });
    cityButton.addEventListener("click", () => {
        byCity = true;
        updateScope();
        if (!citySelect.value) cityField.querySelector(".custom-select-display")?.focus();
    });
    citySelect.addEventListener("change", updateScope);
}
