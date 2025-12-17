/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

function parseConditionJson(el) {
    const raw = el.dataset.conditionJson || "";
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { return null; }
}

function getInputValue(questionEl) {
    const qType = questionEl.dataset.type;
    const inputs = questionEl.querySelectorAll("[name^='q_']");
    if (!inputs.length) return { value: null, value_list: null };

    if (qType === "bool") {
        const cb = inputs[0];
        return { value: cb.checked ? true : false, value_list: null };
    }
    if (qType === "multiselect") {
        const checked = [];
        inputs.forEach((i) => { if (i.checked) checked.push(i.value); });
        return { value: null, value_list: checked };
    }
    if (qType === "file") {
        // File upload not handled in autosave (can be added with multipart route)
        return { value: null, value_list: null };
    }
    const el = inputs[0];
    return { value: el.value, value_list: null };
}

function evaluateCondition(operator, actual, target) {
    const a = actual === null || actual === undefined ? "" : String(actual);
    const t = target === null || target === undefined ? "" : String(target);

    if (operator === "truthy") return Boolean(actual) === true;
    if (operator === "falsy") return Boolean(actual) === false;

    if (operator === "eq") return a === t;
    if (operator === "neq") return a !== t;
    if (operator === "contains") return a.toLowerCase().includes(t.toLowerCase());
    if (operator === "in") {
        const items = t.split(",").map((x) => x.trim()).filter(Boolean);
        return items.includes(a);
    }
    return false;
}

publicWidget.registry.DynamicFormPortal = publicWidget.Widget.extend({
    selector: "#o_df_root",
    events: {
        "change .o_df_question input, change .o_df_question textarea, change .o_df_question select": "_onFieldChange",
        "input .o_df_question input[type='text'], input .o_df_question textarea": "_onFieldInput",
        "click .o_df_steps [data-step-id]": "_onStepClick",
    },

    start() {
        this.submissionId = parseInt(this.el.dataset.submissionId);
        this.csrfToken = this.el.dataset.csrfToken;
        this._indexQuestions();
        this._applyAllConditions();
        return this._super(...arguments);
    },

    _indexQuestions() {
        this.questions = Array.from(this.el.querySelectorAll(".o_df_question"));
        this.byQuestionId = new Map();
        this.questions.forEach((qEl) => {
            const qid = parseInt(qEl.dataset.questionId);
            this.byQuestionId.set(qid, qEl);
        });

        // Build dependency map: depends_on_question_id -> [questionEl...]
        this.dependents = new Map();
        this.questions.forEach((qEl) => {
            const cond = parseConditionJson(qEl);
            if (!cond || !cond.conditions) return;
            cond.conditions.forEach((c) => {
                const depId = parseInt(c.depends_on_question_id);
                if (!this.dependents.has(depId)) this.dependents.set(depId, []);
                this.dependents.get(depId).push(qEl);
            });
        });
    },

    _onStepClick(ev) {
        const li = ev.currentTarget;
        const stepId = li.dataset.stepId;
        const target = this.el.querySelector(`.o_df_step[data-step-id='${stepId}']`);
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    },

    _onFieldInput(ev) {
        // Debounced autosave for typing
        clearTimeout(this._typingTimer);
        const qEl = ev.target.closest(".o_df_question");
        if (!qEl) return;
        this._typingTimer = setTimeout(() => this._autosave(qEl), 600);
    },

    async _onFieldChange(ev) {
        const qEl = ev.target.closest(".o_df_question");
        if (!qEl) return;

        await this._autosave(qEl);

        const changedQid = parseInt(qEl.dataset.questionId);
        const deps = this.dependents.get(changedQid) || [];
        deps.forEach((depEl) => this._applyConditions(depEl));
    },

    _answersSnapshot() {
        // Snapshot current values for condition evaluation
        const snapshot = new Map();
        this.questions.forEach((qEl) => {
            const qid = parseInt(qEl.dataset.questionId);
            const { value, value_list } = getInputValue(qEl);
            snapshot.set(qid, value_list ? value_list.map(String) : value);
        });
        return snapshot;
    },

    _applyAllConditions() {
        this.questions.forEach((qEl) => this._applyConditions(qEl));
    },

    _applyConditions(questionEl) {
        const cond = parseConditionJson(questionEl);
        if (!cond) return;
        const snapshot = this._answersSnapshot();

        const results = (cond.conditions || []).map((c) => {
            const depId = parseInt(c.depends_on_question_id);
            const actual = snapshot.get(depId);
            const operator = c.operator;
            const target = c.value || "";

            // If actual is an array (multiselect), compare as joined string and also contains for 'in'
            if (Array.isArray(actual)) {
                if (operator === "contains") return actual.join(",").toLowerCase().includes(String(target).toLowerCase());
                if (operator === "in") {
                    const items = String(target).split(",").map((x) => x.trim()).filter(Boolean);
                    return actual.some((v) => items.includes(String(v)));
                }
                // For eq/neq, compare joined
                return evaluateCondition(operator, actual.join(","), target);
            }
            return evaluateCondition(operator, actual, target);
        });

        const logic = cond.logic || "all";
        const ok = logic === "any" ? results.some(Boolean) : results.every(Boolean);

        // Toggle visibility
        questionEl.classList.toggle("d-none", !ok);
    },

    async _autosave(questionEl) {
        const qid = parseInt(questionEl.dataset.questionId);
        const statusEl = questionEl.querySelector(".o_df_save_status");
        if (statusEl) statusEl.textContent = "Saving…";

        const payload = getInputValue(questionEl);
        try {
            await rpc(`/my/forms/${this.submissionId}/autosave`, {
                submission_id: this.submissionId,
                question_id: qid,
                value: payload.value,
                value_list: payload.value_list,
            });
            if (statusEl) statusEl.textContent = "Saved";
            setTimeout(() => { if (statusEl) statusEl.textContent = "Saved automatically"; }, 1000);
        } catch (e) {
            if (statusEl) statusEl.textContent = "Save failed. Please retry.";
        }
    },
});
