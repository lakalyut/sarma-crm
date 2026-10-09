// Assortment coverage in the Telegram mini-app; initialized after its shared helpers.
let clientsLoaded = false;
let citiesLoaded = false;
let allClientRows = [];
let clientsMonths = [];
let clientsMonthFrom = null;
let clientsMonthTo = null;
let clientsRequest = 0;
let clientsAbort = null;
let detailRequest = 0;
let detailAbort = null;
let clientsStop = () => {};
let detailStop = () => {};

async function clientsFetch(url, signal) {
    const response = await fetch(url, { headers: authHeader(), signal });
    let body;
    try { body = await response.json(); }
    catch (_) { throw new Error('Не удалось загрузить данные. Перезапустите мини-апп.'); }
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Не удалось загрузить данные.');
    return body;
}

function clientsParams(city) {
    const params = new URLSearchParams();
    if (city) params.set('city', city);
    if (clientsMonthFrom) params.set('month_from', clientsMonthFrom);
    if (clientsMonthTo) params.set('month_to', clientsMonthTo);
    return params;
}

function periodLabel() {
    const label = value => (clientsMonths.find(m => m.value === value) || {}).label || '';
    return clientsMonthFrom === clientsMonthTo ? label(clientsMonthFrom) : label(clientsMonthFrom) + ' — ' + label(clientsMonthTo);
}

function resetClientsPeriod() {
    clientsStop();
    detailStop();
    document.getElementById('clients-list-content').textContent = '';
    clientsRequest++;
    detailRequest++;
    if (clientsAbort) clientsAbort.abort();
    if (detailAbort) detailAbort.abort();
    clientsMonthFrom = null;
    clientsMonthTo = null;
    clientsMonths = [];
    allClientRows = [];
    clientsLoaded = false;
    document.getElementById('clients-search').value = '';
    document.getElementById('clients-period-field').classList.add('is-hidden');
    document.getElementById('clients-list-view').classList.remove('is-hidden');
    document.getElementById('clients-detail-view').classList.add('is-hidden');
}

function renderPeriod(body) {
    clientsMonths = body.months || [];
    clientsMonthFrom = body.month_from;
    clientsMonthTo = body.month_to;
    ['clients-month-from', 'clients-month-to'].forEach(id => {
        const select = document.getElementById(id);
        select.innerHTML = clientsMonths.map(m => '<option value="' + escHtml(m.value) + '">' + escHtml(m.label) + '</option>').join('');
        select.value = id === 'clients-month-from' ? clientsMonthFrom : clientsMonthTo;
    });
    document.getElementById('clients-period-field').classList.toggle('is-hidden', !clientsMonths.length);
}

async function loadClientsForCity(city, resetPeriod = false) {
    if (resetPeriod) resetClientsPeriod();
    const request = ++clientsRequest;
    if (clientsAbort) clientsAbort.abort();
    clientsAbort = new AbortController();
    const el = document.getElementById('clients-list-content');
    const apply = document.getElementById('clients-period-apply');
    const stopLoading = beginLoading(el, { label: 'Загружаем клиентов…', mode: allClientRows.length ? 'line' : 'skeleton', retain: allClientRows.length > 0 });
    clientsStop = stopLoading;
    document.getElementById('clients-search').disabled = true;
    apply.disabled = true;
    try {
        const body = await clientsFetch('/ambassador/app/clients?' + clientsParams(city), clientsAbort.signal);
        if (request !== clientsRequest) return;
        allClientRows = body.rows;
        clientsLoaded = true;
        renderPeriod(body);
        document.getElementById('clients-search').disabled = false;
        filterClientsList();
    } catch (error) {
        if (request !== clientsRequest || error.name === 'AbortError') return;
        clientsLoaded = false;
        el.innerHTML = '<p>' + escHtml(error.message) + '</p><button type="button" class="secondary" id="clients-retry">Повторить</button>';
    } finally {
        stopLoading();
        if (request === clientsRequest) apply.disabled = false;
    }
}

function abcCounts(abc) {
    return '<div class="mini-abc-counts">' + ['A', 'B', 'C'].map(category => {
        const count = abc[category];
        return '<span class="mini-abc-count mini-abc-' + category.toLowerCase() + '">' + category + ': <b>' + count.ordered + ' из ' + count.total + '</b></span>';
    }).join('') + '</div>';
}

function renderClientsList(rows) {
    const el = document.getElementById('clients-list-content');
    if (!rows.length) { el.textContent = 'Клиенты не найдены.'; return; }
    el.innerHTML = rows.map(r =>
        '<div class="lb-row client-summary-row" role="button" tabindex="0" data-client="' + escHtml(r.client) + '" data-sale-type="' + escHtml(r.sale_type) + '">' +
        '<div class="lb-top"><span class="lb-name">' + escHtml(r.client) + '</span><span class="lb-region">' + escHtml(r.sale_type) + '</span></div>' +
        '<div class="hint">Сегмент: ' + escHtml(r.segment || 'не задан') + '</div>' + abcCounts(r.abc) +
        (r.abc.unrated.ordered ? '<div class="hint">Без рейтинга: ' + r.abc.unrated.ordered + ' заказанных SKU</div>' : '') +
        (!r.has_orders ? '<div class="hint">Нет заказов за выбранный период</div>' : '') + '</div>'
    ).join('');
}

function filterClientsList() {
    const q = document.getElementById('clients-search').value.trim().toLowerCase();
    renderClientsList(q ? allClientRows.filter(r => r.client.toLowerCase().includes(q)) : allClientRows);
}

function renderClientDetail(client, saleType, data) {
    document.getElementById('detail-client-name').textContent = client;
    document.getElementById('detail-client-type').textContent = saleType;
    document.getElementById('detail-summary').innerHTML = '<h3 class="mini-assortment-title">Ассортимент по ABC</h3>' +
        '<div class="hint">' + escHtml(periodLabel()) + ' · Сегмент: ' + escHtml(data.segment || 'не задан') + '</div>' +
        '<p class="hint">По покупкам за выбранный период.</p>' +
        (data.groups.length ? '<div class="mini-assortment-counts">' + ['A', 'B', 'C'].map(category => {
            const count = data.abc[category];
            return '<div class="mini-assortment-count mini-abc-' + category.toLowerCase() + '">' +
                '<span>Категория ' + category + ' в ассортименте</span><b>' + count.ordered + ' из ' + count.total + '</b></div>';
        }).join('') + '</div>' : 'Нет данных по клиенту.');
    document.getElementById('detail-sku-list').innerHTML = data.groups.filter(group => group.category !== 'unrated').map(group => {
        const missing = group.items.filter(item => !item.ordered);
        if (!group.total) return '<p class="hint">Категория ' + group.category + ': в сегменте нет SKU.</p>';
        if (!missing.length) return '<div class="mini-assortment-complete">Категория ' + group.category + ': клиент покупает весь ассортимент сегмента за выбранный период.</div>';
        return '<details class="mini-abc-group mini-abc-' + group.category.toLowerCase() + '"' + (group.category === 'A' ? ' open' : '') + '><summary>' +
            'Не покупает из категории ' + group.category + ' (' + missing.length + ')</summary>' +
            '<div class="mini-assortment-tags">' + missing.map(item => '<span class="mini-assortment-tag">' + escHtml(item.name) + '</span>').join('') + '</div></details>';
    }).join('');
}

async function openClientDetail(client, saleType) {
    const request = ++detailRequest;
    if (detailAbort) detailAbort.abort();
    detailAbort = new AbortController();
    const signal = detailAbort.signal;
    document.getElementById('clients-list-view').classList.add('is-hidden');
    document.getElementById('clients-detail-view').classList.remove('is-hidden');
    document.getElementById('detail-client-name').textContent = client;
    document.getElementById('detail-client-type').textContent = saleType;
    const stopLoading = beginLoading(document.getElementById('detail-summary'), { label: 'Загружаем ассортимент…', retain: false });
    detailStop = stopLoading;
    document.getElementById('detail-sku-list').textContent = '';
    renderHistoryInto('detail-history', 'detail-history-list', []);
    const city = currentRole !== 'ambassador' ? selectedClientsCity : null;
    const params = clientsParams(city);
    params.set('client', client);
    params.set('sale_type', saleType);
    const historyParams = new URLSearchParams({ client });
    if (city) historyParams.set('city', city);
    clientsFetch('/ambassador/app/visit-history?' + historyParams, signal)
        .then(body => { if (request === detailRequest) renderHistoryInto('detail-history', 'detail-history-list', body.history); })
        .catch(() => {});
    try {
        const body = await clientsFetch('/ambassador/app/client-detail?' + params, signal);
        if (request === detailRequest) renderClientDetail(client, saleType, body);
    } catch (error) {
        if (request !== detailRequest || error.name === 'AbortError') return;
        const summary = document.getElementById('detail-summary');
        summary.innerHTML = '<p>' + escHtml(error.message) + '</p><button type="button" class="secondary" id="detail-retry">Повторить</button>';
        document.getElementById('detail-retry').addEventListener('click', () => openClientDetail(client, saleType));
    } finally { stopLoading(); }
}

document.getElementById('clients-search').addEventListener('input', filterClientsList);
document.getElementById('clients-list-content').addEventListener('click', event => {
    if (event.target.closest('#clients-retry')) { loadClientsForCity(selectedClientsCity); return; }
    if (document.getElementById('clients-period-apply').disabled) return;
    const row = event.target.closest('.client-summary-row');
    if (row) openClientDetail(row.dataset.client, row.dataset.saleType);
});
document.getElementById('clients-list-content').addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    if (document.getElementById('clients-period-apply').disabled) return;
    const row = event.target.closest('.client-summary-row');
    if (row) { event.preventDefault(); openClientDetail(row.dataset.client, row.dataset.saleType); }
});
document.getElementById('clients-period-apply').addEventListener('click', () => {
    const start = document.getElementById('clients-month-from').value;
    const end = document.getElementById('clients-month-to').value;
    if (start > end) { document.getElementById('clients-list-content').textContent = 'Начало периода не может быть позже окончания.'; return; }
    clientsMonthFrom = start;
    clientsMonthTo = end;
    loadClientsForCity(selectedClientsCity);
});
document.getElementById('clients-back-btn').addEventListener('click', () => {
    detailStop();
    detailRequest++;
    if (detailAbort) detailAbort.abort();
    document.getElementById('clients-detail-view').classList.add('is-hidden');
    document.getElementById('clients-list-view').classList.remove('is-hidden');
});
document.getElementById('clients-city-select').addEventListener('change', function () {
    selectedClientsCity = this.value;
    resetClientsPeriod();
    if (selectedClientsCity) loadClientsForCity(selectedClientsCity);
    else document.getElementById('clients-list-content').textContent = 'Выберите город выше.';
});
