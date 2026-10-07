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
    el.textContent = 'Загружаю...';
    allClientRows = [];
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
    document.getElementById('detail-summary').innerHTML = '<div class="hint">' + escHtml(periodLabel()) + ' · Сегмент: ' + escHtml(data.segment || 'не задан') + '</div>' +
        (data.groups.length ? abcCounts(data.abc) : 'Нет данных по клиенту.');
    document.getElementById('detail-sku-list').innerHTML = data.groups.map(group =>
        '<details class="mini-abc-group" open><summary>' + (group.category === 'unrated' ? 'Без ABC-рейтинга' : 'Категория ' + group.category) +
        ' · Заказано ' + group.ordered + ' из ' + group.total + '</summary>' +
        (group.items.length ? group.items.map(item =>
            '<div class="visit-history-item"><div class="visit-history-goal">' + escHtml(item.name) + '</div>' +
            '<div class="visit-history-meta ' + (item.ordered ? 'mini-ordered' : 'mini-missing') + '">' +
            (item.ordered ? 'Заказан · ' + item.qty.toLocaleString('ru-RU') + ' шт.' : 'Не заказан за период') + '</div></div>'
        ).join('') : '<p class="hint">В этой категории нет SKU.</p>') + '</details>'
    ).join('');
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
    document.getElementById('detail-summary').textContent = 'Загружаю...';
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
        document.getElementById('detail-summary').textContent = error.message;
    }
}

document.getElementById('clients-search').addEventListener('input', filterClientsList);
document.getElementById('clients-list-content').addEventListener('click', event => {
    if (event.target.closest('#clients-retry')) { loadClientsForCity(selectedClientsCity); return; }
    const row = event.target.closest('.client-summary-row');
    if (row) openClientDetail(row.dataset.client, row.dataset.saleType);
});
document.getElementById('clients-list-content').addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
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
