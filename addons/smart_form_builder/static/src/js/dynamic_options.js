(function () {
  "use strict";

  function loadOptions(selectEl) {
    try {
      var fieldId = selectEl.getAttribute("data-field-id") || (selectEl.dataset ? selectEl.dataset.fieldId : null);
      var token = selectEl.getAttribute("data-form-token") || (selectEl.dataset ? selectEl.dataset.formToken : null);
      if (!fieldId) { return; }

      var url = "/smart_form/options/" + encodeURIComponent(fieldId);
      if (token) {
        url += "?token=" + encodeURIComponent(token);
      }

      fetch(url, { method: "GET", credentials: "same-origin" })
        .then(function (res) {
          if (!res || !res.ok) { return null; }
          return res.json();
        })
        .then(function (data) {
          if (!data || !data.success) { return; }

          var firstOpt = selectEl.querySelector("option");
          var placeholder = firstOpt ? firstOpt.cloneNode(true) : null;

          selectEl.innerHTML = "";
          if (placeholder) { selectEl.appendChild(placeholder); }

          var opts = data.options || [];
          for (var i = 0; i < opts.length; i++) {
            var o = opts[i] || {};
            var opt = document.createElement("option");
            opt.value = o.value;
            opt.textContent = o.label;
            selectEl.appendChild(opt);
          }
        })
        .catch(function () {
          // silent
        });
    } catch (e) {
      // silent
    }
  }

  function init() {
    var nodes = document.querySelectorAll("select[data-dynamic-options='1']");
    for (var i = 0; i < nodes.length; i++) {
      loadOptions(nodes[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();