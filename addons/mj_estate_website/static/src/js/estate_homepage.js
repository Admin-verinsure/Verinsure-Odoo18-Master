/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

/**
 * Morris & James.Estate — homepage interactions.
 * No jQuery. IntersectionObserver-driven reveals, a lightweight
 * scroll-linked parallax, sticky/transparent header, mobile menu,
 * and a progressive-disclosure "Read Story" panel.
 */
publicWidget.registry.MJEstateHomepage = publicWidget.Widget.extend({
    selector: ".mj-estate",

    /**
     * @override
     */
    start() {
        this._initStickyHeader();
        this._initMobileMenu();
        this._initFadeUps();
        this._initParallax();
        this._initSmoothScroll();
        this._initExpandPanel();
        this._initNewsletter();
        return this._super(...arguments);
    },

    // -----------------------------------------------------------
    // Sticky / transparent header
    // -----------------------------------------------------------
    _initStickyHeader() {
        const header = this.el.querySelector('[data-mj="header"]');
        if (!header) return;

        const THRESHOLD = 60;
        const onScroll = () => {
            header.classList.toggle("mj-is-stuck", window.scrollY > THRESHOLD);
        };
        onScroll();
        window.addEventListener("scroll", onScroll, { passive: true });
        this._mjOnScrollHandlers = this._mjOnScrollHandlers || [];
        this._mjOnScrollHandlers.push(onScroll);
    },

    // -----------------------------------------------------------
    // Mobile menu toggle
    // -----------------------------------------------------------
    _initMobileMenu() {
        const header = this.el.querySelector('[data-mj="header"]');
        const toggle = this.el.querySelector('[data-mj="menu-toggle"]');
        if (!header || !toggle) return;

        toggle.addEventListener("click", () => {
            const isOpen = header.classList.toggle("mj-menu-open");
            toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        });

        // Close the mobile menu after tapping a link inside it.
        const mobileNav = this.el.querySelector('[data-mj="mobile-menu"]');
        if (mobileNav) {
            mobileNav.addEventListener("click", (ev) => {
                if (ev.target.tagName === "A") {
                    header.classList.remove("mj-menu-open");
                    toggle.setAttribute("aria-expanded", "false");
                }
            });
        }
    },

    // -----------------------------------------------------------
    // Fade-up reveal on scroll (IntersectionObserver)
    // -----------------------------------------------------------
    _initFadeUps() {
        const targets = this.el.querySelectorAll('[data-mj="fade-up"]');
        if (!targets.length) return;

        if (!("IntersectionObserver" in window)) {
            targets.forEach((t) => t.classList.add("mj-in-view"));
            return;
        }

        const io = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        const el = entry.target;
                        const delay = parseInt(el.dataset.mjDelay || "0", 10);
                        if (delay) {
                            el.style.transitionDelay = `${delay}ms`;
                        }
                        el.classList.add("mj-in-view");
                        io.unobserve(el);
                    }
                });
            },
            { threshold: 0.16, rootMargin: "0px 0px -6% 0px" }
        );

        targets.forEach((t) => io.observe(t));
        this._mjIO = io;
    },

    // -----------------------------------------------------------
    // Lightweight parallax on hero + final CTA imagery
    // -----------------------------------------------------------
    _initParallax() {
        const sections = this.el.querySelectorAll('[data-mj="parallax-section"]');
        if (!sections.length) return;

        const reduceMotion = window.matchMedia(
            "(prefers-reduced-motion: reduce)"
        ).matches;
        if (reduceMotion) return;

        let ticking = false;
        const update = () => {
            sections.forEach((section) => {
                const img = section.querySelector('[data-mj="parallax-img"]');
                if (!img) return;
                const rect = section.getBoundingClientRect();
                const vh = window.innerHeight || 1;
                // progress: -1 (above viewport) .. 1 (below viewport)
                const progress = (rect.top / vh);
                const shift = Math.max(-40, Math.min(40, progress * 40));
                img.style.transform = `translateY(${shift}px) scale(1.08)`;
            });
            ticking = false;
        };

        const onScroll = () => {
            if (!ticking) {
                window.requestAnimationFrame(update);
                ticking = true;
            }
        };

        update();
        window.addEventListener("scroll", onScroll, { passive: true });
        window.addEventListener("resize", onScroll, { passive: true });
        this._mjOnScrollHandlers = this._mjOnScrollHandlers || [];
        this._mjOnScrollHandlers.push(onScroll);
    },

    // -----------------------------------------------------------
    // Smooth in-page scroll for [data-mj="scroll-to"] triggers
    // -----------------------------------------------------------
    _initSmoothScroll() {
        const triggers = this.el.querySelectorAll('[data-mj="scroll-to"]');
        triggers.forEach((btn) => {
            btn.addEventListener("click", () => {
                const targetSel = btn.dataset.target;
                const target = targetSel && this.el.querySelector(targetSel);
                if (target) {
                    target.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            });
        });
    },

    // -----------------------------------------------------------
    // Brand Story "Read Story" progressive disclosure
    // -----------------------------------------------------------
    _initExpandPanel() {
        const trigger = this.el.querySelector('[data-mj="expand-trigger"]');
        const panel = this.el.querySelector('[data-mj="expand-panel"]');
        const label = this.el.querySelector('[data-mj="expand-label"]');
        if (!trigger || !panel) return;

        trigger.addEventListener("click", () => {
            const isOpen = panel.classList.toggle("mj-is-open");
            trigger.setAttribute("aria-expanded", isOpen ? "true" : "false");
            if (label) {
                label.textContent = isOpen ? "Close Story" : "Read Story";
            }
        });
    },

    // -----------------------------------------------------------
    // Newsletter — client-side acknowledgement only.
    // No mailing-list backend is wired up in this homepage-only
    // module; replace with a real subscribe action (e.g. Odoo
    // Mailing List Contact) when that infrastructure exists.
    // -----------------------------------------------------------
    _initNewsletter() {
        const form = this.el.querySelector('[data-mj="newsletter"]');
        const note = this.el.querySelector('[data-mj="newsletter-note"]');
        if (!form) return;

        form.addEventListener("submit", (ev) => {
            ev.preventDefault();
            const input = form.querySelector("input[type=email]");
            if (input && input.value && note) {
                note.textContent = "Thanks — you're on the list.";
                form.reset();
            }
        });
    },

    /**
     * @override
     */
    destroy() {
        (this._mjOnScrollHandlers || []).forEach((fn) => {
            window.removeEventListener("scroll", fn);
            window.removeEventListener("resize", fn);
        });
        if (this._mjIO) {
            this._mjIO.disconnect();
        }
        this._super(...arguments);
    },
});

export default publicWidget.registry.MJEstateHomepage;
