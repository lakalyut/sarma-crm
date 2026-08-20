// Мультивыбор через поиск с тегами (клиенты, SKU и т.п.) — общий для
// «Свода», «Амбассадорского отчёта» и «Эффективности визита» на «Анализе по
// клиентам». Рендерится всегда только одна активная вкладка (см. CLAUDE.md),
// поэтому единственный глобальный initTagSearch не конфликтует сам с собой.
function initTagSearch(config) {
    const input = document.getElementById(config.inputId);
    const dropdown = document.getElementById(config.dropdownId);
    const tags = document.getElementById(config.tagsId);

    if (!input || !dropdown || !tags) return;

    const items = Array.from(dropdown.querySelectorAll(".search-dropdown-item"));
    const maxVisible = config.maxVisible || null;
    let expanded = false;
    let moreBtn = null;

    function existingValues() {
        return Array.from(tags.querySelectorAll(`input[name="${config.inputName}"]`)).map(i => i.value);
    }

    function updateCollapse() {
        if (!maxVisible) return;

        const tagEls = Array.from(tags.querySelectorAll(".filter-tag"));

        if (moreBtn) {
            moreBtn.remove();
            moreBtn = null;
        }

        if (tagEls.length <= maxVisible) {
            tagEls.forEach(t => t.classList.remove("is-hidden"));
            return;
        }

        tagEls.forEach((t, i) => {
            t.classList.toggle("is-hidden", !expanded && i >= maxVisible);
        });

        moreBtn = document.createElement("span");
        moreBtn.className = "filter-tag-more";
        moreBtn.textContent = expanded ? "Свернуть" : `+${tagEls.length - maxVisible} ещё`;
        moreBtn.addEventListener("click", function () {
            expanded = !expanded;
            updateCollapse();
        });
        tags.appendChild(moreBtn);
    }

    function attachRemoveHandler(tag) {
        const btn = tag.querySelector(".filter-tag-remove");
        if (!btn) return;

        btn.addEventListener("click", function () {
            tag.remove();
            filterItems();
            updateCollapse();
        });
    }

    function filterItems() {
        const value = input.value.trim().toLowerCase();
        const selected = existingValues();
        let visibleCount = 0;

        items.forEach(item => {
            const text = item.dataset.value.toLowerCase();
            const alreadySelected = selected.includes(item.dataset.value);
            const visible = !alreadySelected && (!value || text.includes(value));

            item.classList.toggle("hidden", !visible);

            if (visible) visibleCount++;
        });

        dropdown.style.display = visibleCount > 0 ? "block" : "none";
    }

    function renderTag(value) {
        const tag = document.createElement("span");
        tag.className = "filter-tag";

        const text = document.createElement("span");
        text.textContent = value;

        const button = document.createElement("button");
        button.type = "button";
        button.className = "filter-tag-remove";
        button.setAttribute("aria-label", "Удалить");
        button.textContent = "×";

        const hiddenInput = document.createElement("input");
        hiddenInput.type = "hidden";
        hiddenInput.name = config.inputName;
        hiddenInput.value = value;

        tag.appendChild(text);
        tag.appendChild(button);
        tag.appendChild(hiddenInput);

        attachRemoveHandler(tag);

        if (moreBtn) {
            tags.insertBefore(tag, moreBtn);
        } else {
            tags.appendChild(tag);
        }
    }

    Array.from(tags.querySelectorAll(".filter-tag")).forEach(attachRemoveHandler);
    updateCollapse();

    input.addEventListener("focus", filterItems);
    input.addEventListener("input", filterItems);

    items.forEach(item => {
        item.addEventListener("click", function () {
            const value = item.dataset.value;

            if (!existingValues().includes(value)) {
                renderTag(value);
                updateCollapse();
            }

            input.value = "";
            dropdown.style.display = "none";
            filterItems();
        });
    });

    document.addEventListener("click", function (e) {
        if (!dropdown.contains(e.target) && e.target !== input) {
            dropdown.style.display = "none";
        }
    });
}
