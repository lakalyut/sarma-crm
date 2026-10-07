const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const flush = () => new Promise(resolve => setImmediate(resolve));

function fixture(fetch) {
    const nodes = new Map();
    const document = {
        getElementById(id) {
            if (!nodes.has(id)) {
                const classes = new Set();
                nodes.set(id, {
                    value: '', textContent: '', innerHTML: '', disabled: false,
                    listeners: {},
                    addEventListener(event, fn) { this.listeners[event] = fn; },
                    classList: {
                        add(name) { classes.add(name); },
                        remove(name) { classes.delete(name); },
                        contains(name) { return classes.has(name); },
                        toggle(name, force) { if (force) classes.add(name); else classes.delete(name); },
                    },
                });
            }
            return nodes.get(id);
        },
    };
    const context = { document, window: { Telegram: { WebApp: { initData: '' } } }, fetch, AbortController, URLSearchParams };
    vm.createContext(context);
    const template = fs.readFileSync(path.join(root, 'app/templates/ambassador/app.html'), 'utf8');
    const scripts = [...template.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)];
    const inline = scripts.filter(match => !match[1].includes('src='));
    vm.runInContext(inline[0][2], context);
    vm.runInContext(fs.readFileSync(path.join(root, 'app/static/js/miniapp_clients.js'), 'utf8'), context);
    vm.runInContext(inline[1][2], context);
    vm.runInContext('currentRole = "user"; selectedClientsCity = "Иркутск";', context);
    return { context, element: id => document.getElementById(id), run: script => vm.runInContext(script, context) };
}

function row(client = 'Кафе') {
    return {
        client, sale_type: 'HoReCa', segment: 'HoReCa', has_orders: true,
        abc: { A: { ordered: 1, total: 2 }, B: { ordered: 0, total: 1 }, C: { ordered: 0, total: 0 }, unrated: { ordered: 0, total: 1 } },
    };
}

function body(client = 'Кафе') {
    return {
        rows: [row(client)], month_from: '2026-06-01', month_to: '2026-06-01',
        months: [{ value: '2026-05-01', label: 'Май 2026' }, { value: '2026-06-01', label: 'Июнь 2026' }],
    };
}

const response = value => ({ ok: true, json: async () => value });

test('template registers tabs; latest month and ABC coverage render', async () => {
    const ui = fixture(async () => response(body()));
    for (const tab of ['visit', 'clients', 'leaderboard']) assert.equal(typeof ui.element('tab-btn-' + tab).listeners.click, 'function');
    await ui.run('loadClientsForCity("Иркутск")');
    assert.equal(ui.element('clients-month-from').value, '2026-06-01');
    assert.match(ui.element('clients-list-content').innerHTML, /A: <b>1 из 2/);
    assert.doesNotMatch(ui.element('clients-list-content').innerHTML, /Вес:/);
});

test('applied period is passed unchanged to list and detail', async () => {
    const urls = [];
    const ui = fixture(async url => {
        urls.push(url);
        if (url.includes('visit-history')) return response({ history: [] });
        if (url.includes('client-detail')) return response({ segment: 'HoReCa', abc: row().abc, groups: [] });
        return response(body());
    });
    await ui.run('loadClientsForCity("Иркутск")');
    ui.element('clients-month-from').value = '2026-05-01';
    ui.element('clients-month-to').value = '2026-06-01';
    // The real server echoes the selected range; emulate that on the second list call.
    ui.context.fetch = async url => {
        urls.push(url);
        if (url.includes('visit-history')) return response({ history: [] });
        if (url.includes('client-detail')) return response({ segment: 'HoReCa', abc: row().abc, groups: [] });
        return response({ ...body(), month_from: '2026-05-01' });
    };
    ui.element('clients-period-apply').listeners.click();
    await flush();
    await ui.run('openClientDetail("Кафе", "HoReCa")');
    const periodUrls = urls.filter(url => url.includes('month_from='));
    assert.equal(periodUrls.length, 2);
    for (const url of periodUrls) {
        const params = new URL(url, 'https://test.local').searchParams;
        assert.equal(params.get('month_from'), '2026-05-01');
        assert.equal(params.get('month_to'), '2026-06-01');
    }
});

test('old city response cannot overwrite current city even if abort is ignored', async () => {
    const pending = [];
    const ui = fixture(() => new Promise(resolve => pending.push(resolve)));
    const first = ui.run('loadClientsForCity("A", true)');
    const second = ui.run('loadClientsForCity("B", true)');
    pending[1](response(body('City B')));
    await second;
    pending[0](response(body('City A')));
    await first;
    assert.match(ui.element('clients-list-content').innerHTML, /City B/);
    assert.doesNotMatch(ui.element('clients-list-content').innerHTML, /City A/);
});

test('city change resets period to server default', async () => {
    const urls = [];
    const ui = fixture(async url => { urls.push(url); return response(body()); });
    await ui.run('loadClientsForCity("A")');
    ui.run('clientsMonthFrom = "2026-05-01";');
    await ui.run('loadClientsForCity("B", true)');
    assert.equal(new URL(urls[1], 'https://test.local').searchParams.has('month_from'), false);
});

test('network failure leaves an actionable retry and does not mark clients loaded', async () => {
    let requests = 0;
    const ui = fixture(async () => {
        requests++;
        if (requests === 1) throw new Error('Offline');
        return response(body());
    });
    await ui.run('loadClientsForCity("Иркутск")');
    assert.match(ui.element('clients-list-content').innerHTML, /clients-retry/);
    assert.equal(ui.run('clientsLoaded'), false);
    ui.element('clients-list-content').listeners.click({ target: { closest: selector => selector === '#clients-retry' ? {} : null } });
    await flush();
    assert.equal(requests, 2);
    assert.equal(ui.run('clientsLoaded'), true);
});

test('assortment card shows only missing aromas and escapes their names', async () => {
    const ui = fixture(async () => response(body()));
    ui.context.detail = {
        segment: 'HoReCa', abc: row().abc,
        groups: [{ category: 'A', ordered: 1, total: 2, items: [
            { name: 'Purchased aroma', qty: 3, ordered: true },
            { name: '<b>Missing</b>', qty: 0, ordered: false },
        ] }],
    };
    ui.run('renderClientDetail("Кафе", "HoReCa", detail)');
    const html = ui.element('detail-sku-list').innerHTML;
    assert.match(ui.element('detail-summary').innerHTML, /Ассортимент по ABC/);
    assert.match(html, /Не покупает из категории A \(1\)/);
    assert.match(html, / open>/);
    assert.match(html, /&lt;b&gt;Missing&lt;\/b&gt;/);
    assert.doesNotMatch(html, /Purchased aroma|<b>Missing<\/b>/);
});

test('assortment card folds B and shows complete categories without missing lists', () => {
    const ui = fixture(async () => response(body()));
    ui.context.detail = { segment: 'HoReCa', abc: row().abc, groups: [
        { category: 'A', total: 1, items: [{ name: 'Bought', ordered: true }] },
        { category: 'B', total: 1, items: [{ name: 'Missing B', ordered: false }] },
        { category: 'C', total: 0, items: [] },
        { category: 'unrated', total: 1, items: [{ name: 'Unrated', ordered: false }] },
    ] };
    ui.run('renderClientDetail("Кафе", "HoReCa", detail)');
    const html = ui.element('detail-sku-list').innerHTML;
    assert.match(html, /Категория A: клиент покупает весь ассортимент/);
    assert.match(html, /Не покупает из категории B \(1\)/);
    assert.match(html, /Категория C: в сегменте нет SKU/);
    assert.doesNotMatch(html, / open>|Unrated|Bought/);
});
