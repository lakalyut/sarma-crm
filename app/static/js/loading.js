// Shared loading feedback. Every request owns its cleanup, including superseded requests.
(() => {
    const logo = document.currentScript.dataset.logo;
    const running = new Map();
    function begin(target, { label = 'Загружаем данные…', mode = 'line', retain = true, button = false } = {}) {
        if (!target) return () => {};
        if (running.has(target)) running.get(target)();
        const previousBusy = target.getAttribute('aria-busy');
        const previousDisabled = target.disabled;
        const previousAriaDisabled = target.getAttribute('aria-disabled');
        const original = button ? Array.from(target.childNodes) : [];
        if (button) {
            target.disabled = true;
            target.setAttribute('aria-disabled', 'true');
        } else if (!retain) target.replaceChildren();
        target.setAttribute('aria-busy', 'true');
        const loader = document.createElement(button ? 'span' : 'div');
        loader.className = 'pulse-loader pulse-loader-' + (button ? 'button' : mode);
        loader.setAttribute('role', 'status');
        loader.setAttribute('aria-live', 'polite');
        const mark = document.createElement('span');
        mark.className = 'pulse-loader-mark';
        const img = document.createElement('img');
        img.src = logo;
        img.alt = '';
        img.width = img.height = button ? 20 : 40;
        mark.append(img);
        const text = document.createElement('span');
        text.textContent = label;
        loader.append(mark, text);
        if (!button && mode !== 'pulse') {
            const track = document.createElement('span');
            track.className = 'pulse-loader-track';
            track.setAttribute('aria-hidden', 'true');
            loader.append(track);
            if (mode === 'skeleton') {
                for (let i = 0; i < 3; i++) {
                    const row = document.createElement('span');
                    row.className = 'pulse-skeleton';
                    row.setAttribute('aria-hidden', 'true');
                    loader.append(row);
                }
            }
        }
        let shown = false;
        let stopped = false;
        const timer = setTimeout(() => {
            if (stopped) return;
            shown = true;
            if (button) target.replaceChildren(loader);
            else if (retain) target.prepend(loader);
            else target.append(loader);
            target.classList.add('pulse-loading-active');
        }, 250);
        const stop = () => {
            if (stopped) return;
            stopped = true;
            clearTimeout(timer);
            loader.remove();
            target.classList.remove('pulse-loading-active');
            if (previousBusy === null) target.removeAttribute('aria-busy');
            else target.setAttribute('aria-busy', previousBusy);
            if (button) {
                if (shown) target.replaceChildren(...original);
                target.disabled = previousDisabled;
                if (previousAriaDisabled === null) target.removeAttribute('aria-disabled');
                else target.setAttribute('aria-disabled', previousAriaDisabled);
            }
            if (running.get(target) === stop) running.delete(target);
        };
        running.set(target, stop);
        return stop;
    }
    window.PulseLoading = { begin };
    window.addEventListener('pageshow', event => {
        if (event.persisted) Array.from(running.values()).forEach(stop => stop());
    });
    document.addEventListener('submit', event => {
        const form = event.target;
        if ((form.method || 'get').toLowerCase() !== 'get' || form.target === '_blank') return;
        const main = document.querySelector('.app-main .app-shell');
        if (main && running.has(main)) { event.preventDefault(); return; }
        queueMicrotask(() => {
            if (event.defaultPrevented) return;
            begin(main, { label: location.pathname.includes('client-analysis') ? 'Готовим отчёт…' : 'Обновляем данные…' });
        });
    });
    document.addEventListener('click', async event => {
        const link = event.target.closest('a[href]');
        if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const url = new URL(link.href, location.href);
        if (url.origin !== location.origin || url.searchParams.get('download') !== '1' || !url.pathname.startsWith('/analytics/')) return;
        event.preventDefault();
        if (link.getAttribute('aria-busy') === 'true') return;
        document.getElementById('pulse-download-error')?.remove();
        const stop = begin(link, { label: 'Готовим отчёт…', button: true });
        try {
            const response = await fetch(url, { credentials: 'same-origin' });
            if (!response.ok || new URL(response.url || url).pathname.startsWith('/auth/')) throw new Error('download');
            const blob = await response.blob();
            const disposition = response.headers.get('content-disposition') || '';
            const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
            const plain = /filename="([^"]+)"/i.exec(disposition);
            const file = document.createElement('a');
            const objectUrl = URL.createObjectURL(blob);
            file.href = objectUrl;
            file.download = encoded ? decodeURIComponent(encoded[1]) : plain ? plain[1] : 'pulse-report.html';
            document.body.append(file);
            file.click();
            file.remove();
            setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
        } catch (_) {
            const message = document.createElement('div');
            message.id = 'pulse-download-error';
            message.className = 'pulse-load-error';
            message.setAttribute('role', 'alert');
            message.textContent = 'Не удалось подготовить отчёт. ';
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.textContent = 'Повторить';
            retry.addEventListener('click', () => link.click());
            message.append(retry);
            link.after(message);
        } finally { stop(); }
    });
})();
