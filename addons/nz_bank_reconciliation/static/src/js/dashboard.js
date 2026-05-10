/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

class AutoReconciliationDashboard extends Component {
    static template = "auto_reconciliation.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            stats: {
                total_runs: 0,
                total_matched: 0,
                bank_matched: 0,
                customer_matched: 0,
                vendor_matched: 0,
                intercompany_matched: 0,
            },
            recentLogs: [],
            companies: [],
            selectedCompanyId: null,
        });

        onWillStart(async () => {
            await this._loadData();
        });
    }

    async _loadData() {
        this.state.loading = true;
        try {
            // Load recent logs (last 10 only — for the activity table)
            const logs = await this.orm.searchRead(
                "auto.reconciliation.log",
                [],
                [
                    "name", "company_id", "triggered_by",
                    "bank_matched", "customer_matched",
                    "vendor_matched", "intercompany_matched",
                    "total_matched", "state", "create_date",
                ],
                { limit: 10, order: "create_date desc" }
            );
            this.state.recentLogs = logs;

            // BUG FIX: Aggregate stats via a single server-side SQL SUM query.
            // The previous approach fetched ALL log records to the browser and
            // used client-side reduce(), which caused browser hangs after
            // months of daily cron runs (1 record/company/day × years = thousands).
            const stats = await this.orm.call(
                "auto.reconciliation.log",
                "get_dashboard_stats",
                [],
                {}
            );
            this.state.stats.total_runs             = stats.total_runs;
            this.state.stats.total_matched          = stats.total_matched;
            this.state.stats.bank_matched           = stats.bank_matched;
            this.state.stats.customer_matched       = stats.customer_matched;
            this.state.stats.vendor_matched         = stats.vendor_matched;
            this.state.stats.intercompany_matched   = stats.intercompany_matched;

            // Load companies with configs
            const configs = await this.orm.searchRead(
                "auto.reconciliation.config",
                [["active", "=", true]],
                ["company_id", "cron_active"]
            );
            this.state.companies = configs;

        } catch (e) {
            console.error("Dashboard load error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    async onRunNow(companyId) {
        try {
            await this.orm.call("auto.reconciliation.engine", "run_all", [], {
                company_ids: [companyId],
                preview_mode: false,
            });
            this.notification.add("Reconciliation completed successfully!", {
                type: "success",
            });
            await this._loadData();
        } catch (e) {
            this.notification.add("Reconciliation failed: " + e.message, {
                type: "danger",
            });
        }
    }

    onOpenLogs() {
        this.action.doAction("nz_bank_reconciliation.action_auto_reconciliation_log");
    }

    onOpenConfig() {
        this.action.doAction("nz_bank_reconciliation.action_auto_reconciliation_config");
    }

    _formatDate(dateStr) {
        if (!dateStr) return "-";
        return new Date(dateStr).toLocaleString();
    }

    _stateClass(state) {
        return {
            done: "badge bg-success",
            running: "badge bg-warning",
            failed: "badge bg-danger",
        }[state] || "badge bg-secondary";
    }
}

registry.category("actions").add("auto_reconciliation_dashboard", AutoReconciliationDashboard);
