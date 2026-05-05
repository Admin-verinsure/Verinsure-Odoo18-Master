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
            // Load recent logs
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

            // Aggregate stats
            const allLogs = await this.orm.searchRead(
                "auto.reconciliation.log",
                [["state", "=", "done"]],
                ["bank_matched", "customer_matched", "vendor_matched", "intercompany_matched", "total_matched"]
            );

            this.state.stats.total_runs = allLogs.length;
            this.state.stats.total_matched = allLogs.reduce((s, l) => s + l.total_matched, 0);
            this.state.stats.bank_matched = allLogs.reduce((s, l) => s + l.bank_matched, 0);
            this.state.stats.customer_matched = allLogs.reduce((s, l) => s + l.customer_matched, 0);
            this.state.stats.vendor_matched = allLogs.reduce((s, l) => s + l.vendor_matched, 0);
            this.state.stats.intercompany_matched = allLogs.reduce((s, l) => s + l.intercompany_matched, 0);

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
        this.action.doAction("nz_bank_recon_v2.action_auto_reconciliation_log");
    }

    onOpenConfig() {
        this.action.doAction("nz_bank_recon_v2.action_auto_reconciliation_config");
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
