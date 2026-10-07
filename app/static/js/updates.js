(function () {
    const editor = document.querySelector('.update-editor');
    const send = document.getElementById('update-send');
    const btn = document.getElementById('update-send-btn');
    let dirty = false;
    function changed() {
        dirty = true;
        btn.disabled = true;
        document.getElementById('update-unsaved').hidden = false;
    }
    editor.addEventListener('input', changed);
    editor.addEventListener('change', changed);
    send.addEventListener('submit', function (event) {
        if (dirty) event.preventDefault();
        else btn.disabled = true;
    });
})();
