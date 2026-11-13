document.querySelectorAll(".help-trigger").forEach(trigger => {
    const panel = document.getElementById(trigger.getAttribute("popovertarget"));
    if (!panel) return;

    function positionPanel() {
        const anchor = trigger.getBoundingClientRect();
        const viewportWidth = document.documentElement.clientWidth;
        const viewportHeight = document.documentElement.clientHeight;
        const gap = 8;
        const edge = 12;
        const below = viewportHeight - anchor.bottom - gap - edge;
        const above = anchor.top - gap - edge;
        panel.style.maxHeight = "";
        const openBelow = panel.offsetHeight <= below || below >= above;
        panel.style.maxHeight = Math.max(0, openBelow ? below : above) + "px";
        panel.style.left = Math.max(edge, Math.min(anchor.left, viewportWidth - panel.offsetWidth - edge)) + "px";
        panel.style.top = (openBelow ? anchor.bottom + gap : anchor.top - gap - panel.offsetHeight) + "px";
    }

    panel.addEventListener("toggle", event => {
        if (event.newState === "open") {
            positionPanel();
            window.addEventListener("resize", positionPanel);
            window.addEventListener("scroll", positionPanel, true);
        } else {
            window.removeEventListener("resize", positionPanel);
            window.removeEventListener("scroll", positionPanel, true);
        }
    });
});
