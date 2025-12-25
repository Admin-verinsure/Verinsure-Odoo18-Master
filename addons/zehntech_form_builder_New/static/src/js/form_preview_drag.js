/** @odoo-module **/

document.addEventListener("DOMContentLoaded", function () {
    const container = document.getElementById("form-builder-preview");
    let dragged = null;

    container.querySelectorAll(".form-field").forEach(field => {
        field.setAttribute("draggable", "true");
    });

    container.addEventListener("dragstart", function (e) {
        if (e.target.classList.contains("form-field")) {
            dragged = e.target;
            e.dataTransfer.effectAllowed = "move";
        }
    });

    container.addEventListener("dragover", function (e) {
        e.preventDefault();
        const target = e.target.closest(".form-field");
        if (dragged && target && dragged !== target) {
            const rect = target.getBoundingClientRect();
            const offset = e.clientY - (rect.top + rect.height / 2);
            if (offset > 0) {
                target.parentNode.insertBefore(dragged, target.nextSibling);
            } else {
                target.parentNode.insertBefore(dragged, target);
            }
        }
    });

    container.addEventListener("drop", function () {
        const fields = container.querySelectorAll(".form-field");
        const sequenceData = Array.from(fields).map((el, index) => ({
            id: parseInt(el.dataset.id),
            sequence: index + 1,
        }));

        fetch("/form_builder/update_sequence", {
    method: "POST",
    headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    },
    body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: {
            sequence_data: sequenceData,
        },
        id: new Date().getTime(),
    }),
})
.then(response => {
            if (!response.ok) throw new Error("Update failed");
            return response.json();
        }).then(data => {
            console.log("Sequence saved!", data);
        }).catch(console.error);
    });
});
