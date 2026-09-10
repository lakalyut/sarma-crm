// Сортировка обычной таблицы по клику на колонку — для лидерборда (и любой
// плоской `.sheet-table` без строки «Итого» и без ранговых статусов, где
// хватает числа/строки). Для SKU-таблиц с «Итого» и рангами New/Lost/A/B/C
// — отдельный `sku_status_table.js::initSortableSkuTable`, не смешивать.
//
// Разметка:
//   <th data-sort-key="visits" data-sort-type="number">Визиты <span class="sort-icon">↕</span></th>
//   <tr data-visits="12" data-ambassador="Иванов">…</tr>
// data-sort-type: "number" (по умолчанию) | "text". Ключ колонки и имя
// data-атрибута строки совпадают (`data-sort-key="visits"` ↔ `data-visits`).
// Клик циклит: убыв. → возр. → без сортировки (как в SKU-таблицах).
function initSortableTable(table) {
    if (!table) return;

    const headers = table.querySelectorAll("th[data-sort-key]");
    const tbody = table.querySelector("tbody");
    if (!headers.length || !tbody) return;

    const originalOrder = Array.from(tbody.querySelectorAll("tr"));
    let state = { key: null, direction: null };

    function cellValue(row, key, type) {
        const raw = row.dataset[key] ?? "";
        return type === "text" ? String(raw).toLowerCase() : parseFloat(raw || "0");
    }

    function updateHeaders() {
        headers.forEach(th => {
            const icon = th.querySelector(".sort-icon");
            const active = th.dataset.sortKey === state.key && state.direction;
            th.classList.toggle("sort-active", Boolean(active));
            if (icon) {
                icon.textContent = active
                    ? state.direction === "asc" ? "↑" : "↓"
                    : "↕";
            }
        });
    }

    function render() {
        updateHeaders();

        if (!state.key || !state.direction) {
            originalOrder.forEach(row => tbody.appendChild(row));
            return;
        }

        const th = table.querySelector('th[data-sort-key="' + state.key + '"]');
        const type = th && th.dataset.sortType === "text" ? "text" : "number";
        const factor = state.direction === "asc" ? 1 : -1;

        Array.from(tbody.querySelectorAll("tr"))
            .sort((a, b) => {
                const av = cellValue(a, state.key, type);
                const bv = cellValue(b, state.key, type);
                if (av < bv) return -1 * factor;
                if (av > bv) return 1 * factor;
                return 0;
            })
            .forEach(row => tbody.appendChild(row));
    }

    headers.forEach(th => {
        th.classList.add("sortable");
        th.addEventListener("click", function () {
            const key = th.dataset.sortKey;
            if (state.key !== key) {
                state = { key: key, direction: "desc" };
            } else if (state.direction === "desc") {
                state.direction = "asc";
            } else {
                state = { key: null, direction: null };
            }
            render();
        });
    });

    render();
}
