(function () {
  "use strict";

  function collectAnswers(formEl) {
    var answers = {};
    var seenRadio = {};
    var seenCheckbox = {};

    var nodes = formEl.querySelectorAll("[data-field-id]");
    for (var k = 0; k < nodes.length; k++) {
      var el = nodes[k];
      var fid = el.getAttribute("data-field-id") || (el.dataset ? el.dataset.fieldId : null);
      if (!fid) { continue; }

      var tag = (el.tagName || "").toLowerCase();
      var type = (el.type || "").toLowerCase();

      if (type === "checkbox") {
        seenCheckbox[fid] = true;
        if (!answers[fid]) { answers[fid] = []; }
        if (el.checked) { answers[fid].push(el.value || "true"); }
        continue;
      }

      if (type === "radio") {
        seenRadio[fid] = true;
        if (el.checked) {
          answers[fid] = el.value;
        }
        continue;
      }

      if (tag === "select") {
        var value = el.value || "";
        var label = "";
        try {
          label = (el.selectedOptions && el.selectedOptions[0]) ? (el.selectedOptions[0].textContent || "").trim() : "";
        } catch (e) {
          label = "";
        }
        answers[fid] = { value: value, label: label };
        continue;
      }

      answers[fid] = (el.value != null) ? String(el.value) : "";
    }

    // Ensure missing radios/checkboxes appear
    for (var r in seenRadio) {
      if (seenRadio.hasOwnProperty(r) && !(r in answers)) { answers[r] = ""; }
    }
    for (var c in seenCheckbox) {
      if (seenCheckbox.hasOwnProperty(c) && !(c in answers)) { answers[c] = []; }
    }

    return answers;
  }

  function evaluateBranching(formEl, cb) {
    cb = cb || function () {};
    var tokenInput = formEl.querySelector("input[name='token']");
    var token = tokenInput ? tokenInput.value : null;
    if (!token) { return cb(null); }

    var answers = collectAnswers(formEl);

    fetch("/smart_form/branching/" + encodeURIComponent(token), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers: answers }),
      credentials: "same-origin"
    })
      .then(function (res) {
        if (!res || !res.ok) { return null; }
        return res.json();
      })
      .then(function (data) {
        if (!data || !data.success) { return cb(null); }
        return cb(data.next_token || null);
      })
      .catch(function () {
        return cb(null);
      });
  }

  function init() {
    var formEl = document.getElementById("smart-form");
    if (!formEl) { return; }

    function maybeUpdateCTA() {
      evaluateBranching(formEl, function (nextToken) {
        var cta = document.getElementById("sfb-branching-cta");
        if (!cta) { return; }
        if (nextToken) {
          cta.style.display = "";
          cta.setAttribute("href", "/smart_form/" + encodeURIComponent(nextToken));
        } else {
          cta.style.display = "none";
          cta.removeAttribute("href");
        }
      });
    }

    formEl.addEventListener("change", function () {
      maybeUpdateCTA();
    });

    formEl.addEventListener("submit", function (ev) {
      evaluateBranching(formEl, function (nextToken) {
        if (nextToken) {
          ev.preventDefault();
          window.location.href = "/smart_form/" + encodeURIComponent(nextToken);
        }
      });
    });

    maybeUpdateCTA();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();