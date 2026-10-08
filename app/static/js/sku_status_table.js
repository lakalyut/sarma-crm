// Сортировка по клику на колонку в таблицах SKU-статусов — общий паттерн
// для детализации клиента (client_detail.html, одна таблица на странице) и
// амбассадорского отчёта (_client_analysis_ambassadors.html, по таблице на
// каждую карточку клиента). STATUS_RANK/ABC_RANK сортируют по значимости
// (Новые → Нестабильные → Потерянные → Существующие; A → B → C), не по
// алфавиту/числу. Опциональная строка "Итого" (tr.amb-sku-total-row)
// остаётся последней после любой сортировки, если она есть в таблице —
// не все таблицы её используют, initSortableSkuTable сама это определяет.
function initSortableSkuTable(table) {
    if (!table) return;

    const sortableHeaders = table.querySelectorAll("th.sortable");
    const tbody = table.querySelector("tbody");

    if (!sortableHeaders.length || !tbody) return;

    const STATUS_RANK = { new: 0, unstable: 1, lost: 2, existing: 3 };
    const ABC_RANK = { A: 0, B: 1, C: 2 };

    let sortState = { key: null, type: null, direction: null };

    function getSortableRows() {
        return Array.from(tbody.querySelectorAll("tr.amb-sku-row"));
    }

    function getTotalRow() {
        return tbody.querySelector("tr.amb-sku-total-row");
    }

    function sortValue(row) {
        if (sortState.type === "status") {
            const rank = STATUS_RANK[row.dataset.status];
            return rank === undefined ? Infinity : rank;
        }
        if (sortState.type === "abc") {
            const rank = ABC_RANK[row.dataset.abc];
            return rank === undefined ? Infinity : rank;
        }
        return parseFloat(row.dataset[sortState.key] || "0");
    }

    function updateHeaderState() {
        sortableHeaders.forEach(th => {
            th.classList.remove("sort-active");
            th.setAttribute("aria-sort", "none");
            const icon = th.querySelector(".sort-icon");
            if (icon) icon.textContent = "↕";

            if (th.dataset.sortKey === sortState.key && sortState.direction) {
                th.classList.add("sort-active");
                th.setAttribute("aria-sort", sortState.direction === "asc" ? "ascending" : "descending");
                if (icon) {
                    icon.textContent = sortState.direction === "asc" ? "↑" : "↓";
                }
            }
        });
    }

    function renderRows() {
        const rows = getSortableRows();
        const totalRow = getTotalRow();

        if (!sortState.key || !sortState.direction) {
            rows.forEach(row => tbody.appendChild(row));
            if (totalRow) tbody.appendChild(totalRow);
            updateHeaderState();
            return;
        }

        const factor = sortState.direction === "asc" ? 1 : -1;
        const isRanked = sortState.type === "status" || sortState.type === "abc";

        rows.sort((a, b) => {
            const av = sortValue(a);
            const bv = sortValue(b);

            if (isRanked) {
                if (av === Infinity && bv === Infinity) return 0;
                if (av === Infinity) return 1;
                if (bv === Infinity) return -1;
            }

            return (av - bv) * factor;
        });

        rows.forEach(row => tbody.appendChild(row));
        if (totalRow) tbody.appendChild(totalRow);

        updateHeaderState();
    }

    sortableHeaders.forEach(th => {
        th.tabIndex = 0;
        if (!th.dataset.keyboardReady) {
            th.dataset.keyboardReady = "1";
            th.addEventListener("keydown", e => {
                if (e.target === th && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault(); th.click();
                }
            });
        }
        th.addEventListener("click", function () {
            const key = th.dataset.sortKey;

            if (sortState.key !== key) {
                sortState.key = key;
                sortState.type = th.dataset.sortType;
                sortState.direction = "desc";
            } else if (sortState.direction === "desc") {
                sortState.direction = "asc";
            } else if (sortState.direction === "asc") {
                sortState.key = null;
                sortState.direction = null;
            } else {
                sortState.direction = "desc";
            }

            renderRows();
        });
    });

    updateHeaderState();
}
