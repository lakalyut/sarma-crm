// Списки-топы с раскрытием «Показать ещё N» (главная и разрез ABC по
// городам, запрос 2026-09-13) — общий модуль вместо двух копий, тот же
// принцип переиспользования, что checkbox_multiselect.js/tag_search.js.
// initExpandableList возвращает {refresh} — тот же паттерн, что у
// initTagSearch(), чтобы внешний код (напр. фильтр) мог пересчитать
// видимость после смены состояния, не завязанного на счётчик кликов.
function initExpandableList(listEl, btnEl, options) {
    const visibleCount = (options && options.visibleCount) || 3;
    let open = false;

    function rows() {
        return Array.from(listEl.children);
    }

    function refresh() {
        const visible = rows().filter(function (r) {
            return !r.classList.contains("is-filtered-out");
        });
        visible.forEach(function (row, i) {
            row.hidden = !open && i >= visibleCount;
        });
        rows()
            .filter(function (r) {
                return r.classList.contains("is-filtered-out");
            })
            .forEach(function (row) {
                row.hidden = true;
            });

        if (!btnEl) return;
        const extra = visible.length - visibleCount;
        if (extra <= 0) {
            btnEl.hidden = true;
            return;
        }
        btnEl.hidden = false;
        btnEl.classList.toggle("is-open", open);
        btnEl.childNodes[0].nodeValue = open
            ? "Свернуть"
            : "Показать ещё " + extra + " ";
    }

    if (btnEl) {
        btnEl.addEventListener("click", function () {
            open = !open;
            refresh();
        });
    }

    refresh();
    return { refresh: refresh };
}
