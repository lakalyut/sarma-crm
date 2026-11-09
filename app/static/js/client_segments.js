(() => {
    const root = document.getElementById('client-segments');
    if (!root) return;
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
