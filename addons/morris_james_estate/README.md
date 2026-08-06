# Morris & James Estate — sample homepage module

This is a reference scaffold, not a finished module. It shows one clean way to
structure a branded Odoo 18 Website homepage: QWeb inheritance + a scoped SCSS
bundle + `website.menu` records for navigation.

## Files
- `__manifest__.py` — depends on `website`, loads the SCSS into `web.assets_frontend`.
- `views/website_templates.xml`
  - `estate_homepage`: inherits `website.homepage`, replaces `#wrap` with the
    hero / story / values / way-finding sections. Each section is wrapped in
    `oe_structure` so an editor can still drop snippets on it in the Website
    Builder — don't remove that class even if you rebuild the markup.
  - Eight `website.menu` records for the primary nav (VISIT / EAT / MAKE /
    DISCOVER / MARKET / LEASE / STORY / CONTACT). Point each `url` at a real
    page once it exists; placeholders won't 404 the site but will show empty
    pages until built.
- `static/src/scss/estate_brand.scss` — every colour and both typefaces as
  named variables, so nothing gets hand-typed as a raw hex code elsewhere.

## Header, logo and nav — a separate template from the homepage body
The header (logo mark + primary nav + "Book a Table" button) lives in
`website.layout`'s `#top`, not in `website.homepage`. Don't try to inject it
via the homepage template above — either:
- Use **Website > Edit > Header** in the Website Builder to set the logo
  image and menu, or
- Add a small separate `inherit_id="website.layout"` template targeting
  `#top` if you need version-controlled control over it.

Either way, the header needs an actual **art-mark logo file** (an SVG/PNG of
the compact plate-derived icon, distinct from the larger circular plate
photography used in the hero) — that's still pending the rights/vector work
called out in the brand manual (section 21: confirm permission before
adapting the plate artwork; section 23: commission the vector redraw). Until
that's resolved, use a placeholder mark rather than the real plate artwork.

"Book a Table" is fine as a header CTA — it's a café reservation, not the
"Book a stay" accommodation language the manual specifically rules out.

## What the homepage template now includes
- Hero (two CTAs: solid "Explore the Estate", outline "Who We Are")
- Tagline banner
- Values (five, numbered — matches the manual's own numbered list)
- **Our Story** — pull quote + copy from Brand Manual section 03
- Way-finding tiles (six glaze-colour categories)
- **Visit Us / map** — address, hours and parking are placeholders; swap in
  the real address before publishing, and replace the OpenStreetMap embed
  with Google Maps if the estate has a Business Profile to link.

## Install
1. Drop the `morris_james_estate` folder into your addons path.
2. Add the Google Fonts (or self-hosted equivalents) for **Cormorant Garamond**
   and **Source Sans 3** — either via `<link>` in a template asset or vendored
   under `static/src/fonts/`.
3. Update Apps list, install the module.
4. If `website.homepage` inheritance conflicts with an existing homepage
   customization, use **Website > Pages > Homepage** instead: create a new
   page from this template's markup and set it as the homepage in
   Website Settings, rather than fighting two inherited views.

## Brand constraints worth keeping in the actual build
These came directly from the brand manual and are easy to lose once real
snippets start getting dragged in:
- No oval frame, no bicycle device, anywhere in the mark or as decoration.
- Glaze colours (the six tile colours) are called out in the manual as
  "controlled flashes" for section markers and way-finding — not a palette to
  spread across the whole page. Core palette carries most of the surface.
- CTA copy is "Explore the Estate" — the manual explicitly says not to use
  "Book a stay" or resort-style language unless accommodation becomes a real,
  approved part of the offering.
- Voice: specific and material ("the kilns have stopped, but the workshops...")
  over generic lifestyle language ("timeless design", "hidden gem").
- Photography direction (if a hero image replaces the SVG device later): real
  place/material/people, natural light, no heavy filters or fake patina.
