odoo.define('your_module_name.club_filter', function (require) {
    "use strict";

    const publicRoot = require('web.public_root');

    publicRoot.ready(function () {
        const clubTypeSelect = document.getElementById("club_type");
        const clubSelect = document.querySelector("select[name='rotary_club_id']");

        if (!clubTypeSelect || !clubSelect) return;

        const allOptions = Array.from(clubSelect.querySelectorAll("option"));

        clubTypeSelect.addEventListener("change", function () {
            const selectedType = this.value;

            // Reset dropdown
            clubSelect.innerHTML = "";
            clubSelect.appendChild(allOptions[0]); // "-- Select a Club --"

            // Show only clubs that match selected type
            allOptions.forEach(opt => {
                if (opt.value && (!selectedType || opt.dataset.type === selectedType)) {
                    clubSelect.appendChild(opt);
                }
            });
        });
    });
});
