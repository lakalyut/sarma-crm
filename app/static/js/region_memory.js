window.PulseRegionMemory = (function () {
    const KEY = "pulse_last_region";

    function save(value) {
        if (!value) return;
        try {
            localStorage.setItem(KEY, value);
        } catch (e) {
            console.warn("Не удалось сохранить последний регион:", e);
        }
    }

    function get() {
        try {
            return localStorage.getItem(KEY) || "";
        } catch (e) {
            return "";
        }
    }

    return { save, get };
})();
