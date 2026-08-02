document.addEventListener("DOMContentLoaded", function () {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (!meta || !meta.content) return;

    const token = meta.content;

    document.querySelectorAll("form").forEach(function (form) {
        const method = (form.getAttribute("method") || "get").toLowerCase();
        if (method !== "post") return;
        if (form.querySelector('input[name="csrf_token"]')) return;

        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "csrf_token";
        input.value = token;
        form.appendChild(input);
    });
});
