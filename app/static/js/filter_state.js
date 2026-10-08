// Общее выбранное состояние фильтров. Значения форм и правила отправки не меняются.
function initFilterStates(root = document) {
    const selector = '.filter-field:not(.filter-actions-row), .clients-mobile-type, [data-filter-field]';
    const fields = Array.from(root.querySelectorAll(selector));
    const groups = new Map();
    fields.forEach(field => {
        const container = field.closest('form') || field.parentElement;
        if (!groups.has(container)) groups.set(container, []);
        groups.get(container).push(field);
    });

    function hasValue(control) {
        if (control.dataset.filterTags) {
            const tags = document.getElementById(control.dataset.filterTags);
            return !!tags && tags.closest('form') === control.closest('form') &&
                !!tags.querySelector('input[type="hidden"][name]');
        }
        if ((!control.name && !control.closest('[data-filter-field]')) || ['csrf_token', 'tab'].includes(control.name)) return false;
        if (['checkbox', 'radio'].includes(control.type)) return control.checked;
        const neutral = control.dataset.filterEmpty ?? '';
        return control.value.trim() !== neutral;
    }

    groups.forEach((groupFields, container) => {
        if (container.dataset.filterStatesReady) return;
        container.dataset.filterStatesReady = '1';
        function update() {
            groupFields.forEach(field => {
                const controls = Array.from(field.querySelectorAll('input, select'));
                field.classList.toggle('filter-selected', controls.some(hasValue));
            });
        }
        let scheduled = false;
        function scheduleUpdate() {
            if (scheduled) return;
            scheduled = true;
            requestAnimationFrame(() => { scheduled = false; update(); });
        }
        container.addEventListener('input', update);
        container.addEventListener('change', update);
        container.addEventListener('display-sync', update, true);
        // reset применяется браузером после события, поэтому читаем новые значения позже.
        container.addEventListener('reset', scheduleUpdate);
        // Теги и AJAX-списки меняются программно. Наблюдаем только содержимое
        // контейнера фильтров, а не всю страницу; классы не вызывают новый проход.
        new MutationObserver(scheduleUpdate).observe(container, { childList: true, subtree: true });
        update();
    });
}
document.addEventListener('DOMContentLoaded', () => initFilterStates());
