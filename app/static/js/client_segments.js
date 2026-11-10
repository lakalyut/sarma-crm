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
    let selected = '';
    function filter() {
        const query = search.value.trim().toLocaleLowerCase('ru');
        let count = 0;
        rows.forEach(row => {
            row.hidden = Boolean((selected && row.dataset.class !== selected) || !row.dataset.client.toLocaleLowerCase('ru').includes(query));
            if (!row.hidden) count += 1;
        });
        buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.segment === selected)));
        root.querySelector('#segments-count').textContent = `Клиентов показано ${count} из ${rows.length}`;
        root.querySelector('#segments-empty').hidden = count > 0;
    }
    buttons.forEach(button => button.addEventListener('click', () => {
        selected = button.dataset.segment;
        filter();
    }));
    search.addEventListener('input', filter);
    filter();
})();
