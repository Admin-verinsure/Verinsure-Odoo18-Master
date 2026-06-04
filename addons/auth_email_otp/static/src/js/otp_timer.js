/**
 * auth_email_otp/static/src/js/otp_timer.js
 * ==========================================
 * Handles:
 *  1. OTP expiry countdown (5 minutes)
 *  2. Resend button cooldown countdown
 *  3. Auto-submit form when OTP input reaches 6 digits (UX convenience)
 *
 * No external dependencies — pure vanilla JS.
 * Runs only on pages containing #otp-countdown (OTP verify page).
 * Does NOT modify any global Odoo state.
 */

(function () {
    "use strict";

    /**
     * Format seconds as M:SS string.
     * @param {number} totalSeconds
     * @returns {string}
     */
    function formatTime(totalSeconds) {
        const m = Math.floor(totalSeconds / 60);
        const s = totalSeconds % 60;
        return m + ":" + String(s).padStart(2, "0");
    }

    /**
     * Start the OTP expiry countdown.
     * Shows remaining time and adds urgency styling in the last 60s.
     * @param {HTMLElement} countdownEl - Element showing the countdown.
     * @param {number} durationSeconds  - Total duration in seconds.
     */
    function startExpiryCountdown(countdownEl, durationSeconds) {
        let remaining = durationSeconds;

        function tick() {
            if (remaining <= 0) {
                countdownEl.textContent = "Expired";
                countdownEl.classList.add("otp-countdown-urgent");
                // Disable submit button
                var submitBtn = document.querySelector(".otp-btn-primary");
                if (submitBtn) {
                    submitBtn.disabled = true;
                    submitBtn.title = "This code has expired. Please request a new one.";
                }
                return;
            }

            countdownEl.textContent = formatTime(remaining);

            // Add urgency styling under 60 seconds
            if (remaining <= 60) {
                countdownEl.classList.add("otp-countdown-urgent");
            } else {
                countdownEl.classList.remove("otp-countdown-urgent");
            }

            remaining -= 1;
            setTimeout(tick, 1000);
        }

        tick();
    }

    /**
     * Start the resend button cooldown.
     * Enables the button and clears countdown text when it reaches 0.
     * @param {HTMLElement} resendBtn        - The resend submit button.
     * @param {HTMLElement} resendCountdown  - Span showing remaining seconds.
     * @param {number} cooldownSeconds       - Seconds until resend is allowed.
     */
    function startResendCooldown(resendBtn, resendCountdown, cooldownSeconds) {
        let remaining = cooldownSeconds;

        function tick() {
            if (remaining <= 0) {
                resendBtn.disabled = false;
                if (resendCountdown) {
                    resendCountdown.parentNode.removeChild(resendCountdown);
                }
                return;
            }
            if (resendCountdown) {
                resendCountdown.textContent = remaining + "s";
            }
            remaining -= 1;
            setTimeout(tick, 1000);
        }

        tick();
    }

    /**
     * Auto-submit the OTP form when exactly 6 numeric digits are entered.
     * Improves UX on mobile (no need to tap "Verify").
     * @param {HTMLInputElement} input - OTP input element.
     */
    function setupAutoSubmit(input) {
        input.addEventListener("input", function () {
            // Strip non-digit characters (safety)
            var cleaned = input.value.replace(/\D/g, "").slice(0, 6);
            input.value = cleaned;

            if (cleaned.length === 6) {
                var form = input.closest("form");
                if (form) {
                    // Small delay for visual feedback
                    setTimeout(function () { form.submit(); }, 120);
                }
            }
        });
    }

    /**
     * Initialise all OTP page behaviour.
     * Guards against running on other pages.
     */
    function init() {
        var countdownEl = document.getElementById("otp-countdown");
        if (!countdownEl) {
            return; // Not the OTP page
        }

        // ── Expiry countdown ───────────────────────────────────────────────
        // 5 minutes = 300 seconds
        startExpiryCountdown(countdownEl, 300);

        // ── Resend cooldown ────────────────────────────────────────────────
        var resendCountdown = document.getElementById("resend-countdown");
        var resendBtn = document.getElementById("otp-resend-btn");

        if (resendBtn && resendCountdown) {
            var seconds = parseInt(resendCountdown.dataset.seconds || "0", 10);
            if (seconds > 0) {
                startResendCooldown(resendBtn, resendCountdown, seconds);
            }
        }

        // ── Auto-submit ────────────────────────────────────────────────────
        var otpInput = document.getElementById("otp_code");
        if (otpInput) {
            setupAutoSubmit(otpInput);
            // Focus the input on page load (autofocus attr handles it natively,
            // but this ensures it works even if autofocus is blocked)
            otpInput.focus();
        }
    }

    // Wait for DOM to be ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();
