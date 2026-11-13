(function () {
    const root = document.documentElement;
    try {
        if (localStorage.getItem("pulse-theme") === "dark") root.dataset.theme = "dark";
    } catch {}

    document.addEventListener("click", event => {
        const button = event.target.closest("[data-theme-toggle]");
        if (!button) return;
        const dark = root.dataset.theme !== "dark";
        root.dataset.theme = dark ? "dark" : "light";
        button.setAttribute("aria-pressed", String(dark));
        try {
            localStorage.setItem("pulse-theme", root.dataset.theme);
        } catch {}
        document.dispatchEvent(new Event("pulse-theme-change"));
    });

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-theme-toggle]").forEach(button => {
            button.setAttribute("aria-pressed", String(root.dataset.theme === "dark"));
        });
    });
})();
