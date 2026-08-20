// Общая логика формы визита амбассадора — используется и в браузерной
// версии (ambassador/visit.html), и в Telegram-мини-аппе (ambassador/app.html).
// Два пути входа реализованы отдельно (см. CLAUDE.md, горизонт 13) из-за
// сетевой ненадёжности VPS→Telegram — это про backend/auth, не про то, что
// сама группировка товаров/фильтр клиентов должны отличаться. Разметка
// списков в каждом шаблоне своя (браузер — search-dropdown-item, мини-апп —
// client-list-item/category-group), поэтому здесь только чистые функции без
// обращения к DOM — рендер остаётся в шаблоне.

// Группирует товары по категории для блока "Ароматы", резолвит ABC-бейдж
// по сегменту, угаданному из типа точки (тот же rating_by_segment, что и
// на веб-аналитике).
function groupProductsByCategory(products, segmentId, abcBySegment) {
    const ratings = (segmentId !== undefined && abcBySegment[segmentId]) || {};
    const byCategory = {};

    for (const p of products) {
        (byCategory[p.category] = byCategory[p.category] || []).push(p);
    }

    return Object.keys(byCategory).sort().map(category => ({
        category,
        items: byCategory[category].map(p => ({
            product: p,
            abc: ratings[p.id] || null,
            searchKey: (p.brand + " " + p.flavor + " " + (p.sku || "")).toLowerCase()
        }))
    }));
}

// Фильтрует список клиентов города по подстроке, с тем же лимитом (30), что
// использовался в обоих шаблонах — не выводить весь список сразу на городах
// с большим числом клиентов.
function filterClientList(clients, filterText) {
    const q = filterText.trim().toLowerCase();
    const matches = q ? clients.filter(c => c.toLowerCase().includes(q)) : clients;
    return matches.slice(0, 30);
}
