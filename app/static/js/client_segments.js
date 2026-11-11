(() => {
    const root = document.getElementById('client-segments');
    if (!root) return;
    const city = root.querySelector('#segments-city');
    const type = root.querySelector('#segments-type');
    const submit = root.querySelector('button[type="submit"]');
    const modeButtons = Array.from(root.querySelectorAll('button[data-mode]'));
    modeButtons.forEach(button => button.addEventListener('click', () => {
        if (submit.disabled) return;
        root.querySelector('input[name="mode"]').value = button.dataset.mode;
        root.querySelector('form').requestSubmit(submit);
    }));
    const status = root.querySelector('#segments-options-status');
    let optionsRequest;
    city.addEventListener('change', async () => {
        if (optionsRequest) optionsRequest.abort();
        const request = new AbortController();
        optionsRequest = request;
        type.replaceChildren(new Option('Все типы', ''));
        type.disabled = true;
        submit.disabled = true;
        modeButtons.forEach(button => { button.disabled = true; });
        type.dispatchEvent(new Event('display-sync', { bubbles: true }));
        status.textContent = 'Загружаем типы точки…';
        status.hidden = false;
        try {
            const url = new URL('/api/clients/abc-xyz/options', window.location.origin);
            url.searchParams.set('city', city.value);
            const response = await fetch(url, { signal: request.signal, credentials: 'same-origin' });
            if (!response.ok) throw new Error('Options unavailable');
            const data = await response.json();
            if (!Array.isArray(data.types) || !data.types.every(value => typeof value === 'string')) {
                throw new Error('Invalid options');
            }
            if (optionsRequest !== request) return;
            type.replaceChildren(new Option('Все типы', ''), ...data.types.map(value => new Option(value, value)));
            status.hidden = true;
        } catch (error) {
            if (optionsRequest !== request) return;
            status.textContent = 'Типы не загрузились. Нажмите «Показать», чтобы обновить страницу.';
        } finally {
            if (optionsRequest === request) {
                type.disabled = false;
                submit.disabled = false;
                modeButtons.forEach(button => { button.disabled = false; });
                type.dispatchEvent(new Event('display-sync', { bubbles: true }));
            }
        }
    });
    root.querySelectorAll('form select').forEach(select => select.addEventListener('change', () => {
        root.querySelector('input[name="complete"]').checked = false;
    }));
    root.querySelector('form').addEventListener('change', () => {
        root.querySelector('#segments-pending').hidden = false;
    });
    const search = root.querySelector('#segments-search');
    if (!search) return;
    const rows = Array.from(root.querySelectorAll('tr[data-client]'));
    const buttons = Array.from(root.querySelectorAll('button[data-segment]'));
    const card = root.querySelector('#segment-client-card');
    const details = root.querySelector('#segment-client-details');
    const count = root.querySelector('#segments-count');
    const empty = root.querySelector('#segments-empty');
    let selected = '';
    let currentClient;

    function matchesSegment(row, segment) {
        if (segment === 'a-gaps') return row.dataset.aGaps === 'true';
        if (segment === 'last-gap') return row.dataset.lastGap === 'true';
        return !segment || row.dataset.class === segment;
    }

    function selectClient(row) {
        currentClient?.querySelector('.segment-client').setAttribute('aria-pressed', 'false');
        currentClient = row;
        card.hidden = !row;
        details.replaceChildren();
        if (row) {
            row.querySelector('.segment-client').setAttribute('aria-pressed', 'true');
            details.append(row.querySelector('template').content.cloneNode(true));
        }
    }

    function filter() {
        const query = search.value.trim().toLocaleLowerCase('ru');
        const visible = rows.filter(row => {
            row.hidden = !matchesSegment(row, selected) || !row.dataset.client.toLocaleLowerCase('ru').includes(query);
            return !row.hidden;
        });
        buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.segment === selected)));
        count.textContent = `Клиентов показано ${visible.length} из ${rows.length}`;
        empty.hidden = visible.length > 0;
        if (!visible.includes(currentClient)) selectClient(visible[0]);
    }

    buttons.forEach(button => {
        const filterCount = button.querySelector('[data-filter-count]');
        if (filterCount && !button.disabled) {
            filterCount.textContent = `· ${rows.filter(row => matchesSegment(row, button.dataset.segment)).length}`;
        }
        button.addEventListener('click', () => {
            selected = selected === button.dataset.segment ? '' : button.dataset.segment;
            filter();
        });
    });
    rows.forEach(row => row.querySelector('.segment-client').addEventListener('click', () => {
        selectClient(row);
        if (window.matchMedia('(max-width: 900px)').matches) card.focus();
    }));
    search.addEventListener('input', filter);
    filter();
})();
