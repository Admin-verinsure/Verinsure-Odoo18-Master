/**
 * auth_2fa_email – OTP page interactive behaviour
 *
 * - Auto-advance focus through digit boxes
 * - Backspace handling
 * - Paste support (paste anywhere in the row)
 * - Assembles digits into the hidden <input name="otp_code"> on submit
 * - 10-minute countdown timer; warns when < 60 s remain
 * - Disables / enables the submit button based on digit completeness
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        const digits     = Array.from(document.querySelectorAll('.otp-digit'));
        const hiddenCode = document.getElementById('otp_hidden');
        const submitBtn  = document.getElementById('otp_submit_btn');
        const countdownEl = document.getElementById('otp_countdown');
        const form       = document.getElementById('otp_form');

        if (!digits.length || !hiddenCode) return;

        // ---- 1. Enable / disable submit ----
        function updateSubmit() {
            const code = digits.map(d => d.value).join('');
            if (hiddenCode) hiddenCode.value = code;
            const complete = code.length === 6 && /^\d{6}$/.test(code);
            submitBtn.disabled = !complete;
            digits.forEach(d => {
                d.classList.toggle('is-filled', d.value.length === 1);
            });
        }

        // ---- 2. Input handling ----
        digits.forEach(function (input, idx) {
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Backspace') {
                    if (input.value) {
                        input.value = '';
                    } else if (idx > 0) {
                        digits[idx - 1].focus();
                        digits[idx - 1].value = '';
                    }
                    updateSubmit();
                    e.preventDefault();
                } else if (e.key === 'ArrowLeft' && idx > 0) {
                    digits[idx - 1].focus();
                } else if (e.key === 'ArrowRight' && idx < digits.length - 1) {
                    digits[idx + 1].focus();
                }
            });

            input.addEventListener('input', function () {
                // Strip non-digits
                input.value = input.value.replace(/\D/g, '').slice(-1);
                if (input.value && idx < digits.length - 1) {
                    digits[idx + 1].focus();
                }
                updateSubmit();
            });

            // Allow overwrite on focus-click
            input.addEventListener('click', function () {
                input.select();
            });
        });

        // ---- 3. Paste handling ----
        digits.forEach(function (input, idx) {
            input.addEventListener('paste', function (e) {
                e.preventDefault();
                const pasted = (e.clipboardData || window.clipboardData)
                    .getData('text')
                    .replace(/\D/g, '')
                    .slice(0, 6);
                pasted.split('').forEach(function (ch, i) {
                    if (digits[i]) digits[i].value = ch;
                });
                const focusIdx = Math.min(pasted.length, digits.length - 1);
                digits[focusIdx].focus();
                updateSubmit();
            });
        });

        // ---- 4. Form submit – assemble code ----
        if (form) {
            form.addEventListener('submit', function () {
                const code = digits.map(d => d.value).join('');
                hiddenCode.value = code;
            });
        }

        // ---- 5. Auto-focus first digit ----
        digits[0].focus();

        // ---- 6. Countdown timer (10 minutes = 600 s) ----
        if (countdownEl) {
            var secondsLeft = 600;

            function tick() {
                secondsLeft -= 1;
                if (secondsLeft < 0) {
                    countdownEl.textContent = '00:00';
                    countdownEl.classList.add('expiring-soon');
                    submitBtn.disabled = true;
                    return;
                }
                var m = String(Math.floor(secondsLeft / 60)).padStart(2, '0');
                var s = String(secondsLeft % 60).padStart(2, '0');
                countdownEl.textContent = m + ':' + s;
                if (secondsLeft <= 60) {
                    countdownEl.classList.add('expiring-soon');
                } else {
                    countdownEl.classList.remove('expiring-soon');
                }
                setTimeout(tick, 1000);
            }

            setTimeout(tick, 1000);
        }
    });
}());
