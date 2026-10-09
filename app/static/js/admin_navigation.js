document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-admin-group]').forEach(group => {
        const key = 'pulseAdminGroup:' + group.dataset.adminGroup;
        try {
            const saved = localStorage.getItem(key);
            if (group.dataset.active !== 'true' && saved !== null) group.open = saved === '1';
        } catch (_) {}
        group.addEventListener('toggle', () => {
            try { localStorage.setItem(key, group.open ? '1' : '0'); } catch (_) {}
        });
    });
});
