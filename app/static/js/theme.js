(function () {
    const root = document.documentElement;
    try {
        if (localStorage.getItem("pulse-theme") === "dark") root.dataset.theme = "dark";
    } catch {}

    document.addEventListener("click", event => {
        const button = event.target.closest("[data-theme-toggle]");
        if (!button) return;
        const dark = root.dataset.theme !== "dark";
        function applyTheme() {
            root.dataset.theme = dark ? "dark" : "light";
            button.setAttribute("aria-pressed", String(dark));
            try {
                localStorage.setItem("pulse-theme", root.dataset.theme);
            } catch {}
            document.dispatchEvent(new Event("pulse-theme-change"));
        }

        if (root.classList.contains("theme-changing")) return;
        if (!document.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches) {
            applyTheme();
            return;
        }

        root.classList.add("theme-changing");
        const transition = document.startViewTransition(applyTheme);
        transition.finished.then(
            () => root.classList.remove("theme-changing"),
            () => root.classList.remove("theme-changing")
        );
    });

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-theme-toggle]").forEach(button => {
            button.setAttribute("aria-pressed", String(root.dataset.theme === "dark"));
        });
    });
})();
