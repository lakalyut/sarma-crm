// Поведение карточек амбассадорского отчёта: сворачивание SKU, сортировка
// таблиц, фильтр по статусу. Общий файл для страницы
// (_client_analysis_ambassadors.html) и для автономной HTML-выгрузки
// (analytics/export/ambassadors_report.html, там вшивается инлайном вместе с
// sku_status_table.js — без сервера скачанный файл ничего не подгрузит).
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".amb-toggle, .amb-link-toggle").forEach(btn => {
        btn.addEventListener("click", function () {
            const targetId = btn.dataset.target;
            const box = document.getElementById(targetId);
            if (!box) return;

            const hidden = box.classList.toggle("is-hidden");
            const expanded = !hidden;

            document.querySelectorAll(`[data-target="${targetId}"]`).forEach(linkedBtn => {
                linkedBtn.setAttribute("aria-expanded", expanded ? "true" : "false");

                if (linkedBtn.classList.contains("amb-link-toggle")) {
                    linkedBtn.textContent = expanded ? "Скрыть SKU" : "Показать SKU";
                }
            });
        });
    });
});

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".amb-card").forEach(card => {
        card.querySelectorAll(".sheet-table").forEach(initSortableSkuTable);
    });
});

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".amb-card").forEach(card => {
        const filterBox = card.querySelector("[data-status-filter]");
        const rows = Array.from(card.querySelectorAll(".amb-sku-row"));

        if (!filterBox || !rows.length) return;

        const statuses = Array.from(new Set(rows.map(row => row.dataset.status).filter(Boolean)));

        const statusLabels = {
            all: "Все",
            new: "Новые у клиента",
            lost: "Пропали",
            unstable: "Нестабильные",
            existing: "Были с начала"
        };

        const statusOrder = ["new", "lost", "unstable", "existing"];
        const availableStatuses = ["all", ...statusOrder.filter(status => statuses.includes(status))];

        function countFor(status) {
            return status === "all" ? rows.length : rows.filter(row => row.dataset.status === status).length;
        }

        filterBox.innerHTML = availableStatuses.map(status => `
            <button
                type="button"
                class="amb-status-filter-btn ${status === "all" ? "active" : ""}"
                data-status="${status}"
            >
                ${statusLabels[status]} (${countFor(status)})
            </button>
        `).join("");

        const buttons = Array.from(filterBox.querySelectorAll(".amb-status-filter-btn"));

        buttons.forEach(button => {
            button.addEventListener("click", function () {
                const selectedStatus = button.dataset.status;

                buttons.forEach(btn => {
                    btn.classList.toggle("active", btn === button);
                });

                rows.forEach(row => {
                    const isVisible = selectedStatus === "all" || row.dataset.status === selectedStatus;
                    row.style.display = isVisible ? "" : "none";
                });
            });
        });
    });
});
