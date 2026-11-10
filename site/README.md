# extremec.com redesign

A static, dependency-free site for Extreme Construction & Rehab (Addison, TX). It has three pages, `index.html`, `services.html`, and `about.html`, plus `assets/styles.css` and `assets/main.js`. You can host it anywhere (Netlify, Cloudflare Pages, GitHub Pages, cPanel) by uploading the `site/` folder. Don't upload `_src/`.

Edit `index.html` directly. Edit the services and about page bodies in `_src/*.main.html`, then run `python3 site/_src/build.py`. That rebuilds both pages with the homepage's head, header, footer, and icons.

## Fix before anything else: the live site is broken

When I tried to load extremec.com on 2026-11-10, HTTPS failed with **an expired SSL certificate**. Plain HTTP returned 406 and 503 errors. Browsers show visitors a full-page security warning on an expired certificate, so the current site loses nearly every visitor before they see any design. Renew the certificate (free with Let's Encrypt or your host's AutoSSL) no matter which site you run.

## Before launch: verify these claims with the owner

I couldn't read the original site, so I built this copy from public directory listings (ZoomInfo, Houzz, Angi, BBB, The Blue Book): founded 1991, based in Addison TX, general contractor doing commercial, apartment, and residential rehab, with trades including plumbing, flooring, electrical, roofing, and HVAC. **Everything below is my inference and needs owner confirmation:**

| Claim | Where it appears |
|---|---|
| Phone (214) 559-5799 is the main line. Listings also show (972) 533-7230 and (972) 380-8686. | Everywhere |
| Business hours Mon–Fri 8am–5pm | Contact section, footer |
| Callback within one business day ("24h") | Stats, contact, form |
| Carries general liability + workers' comp; licensed trades in-house | FAQ |
| Pulls permits, handles inspections | FAQ, services |
| Fixed itemized bids, written change orders, written schedule | Process, commitments |
| Cities served (Dallas, Plano, Richardson, Carrollton, Farmers Branch, Irving, Frisco, Fort Worth) | FAQ, schema |
| **About-page timeline (1990s multifamily, 2000s commercial)** | about.html. This history is a plausible draft, not fact. Rewrite it with the owner's real story. |
| Business name: listings show "Extreme Construction," "Extreme Construction & Rehab," and "Extreme Commercial Construction" | Everywhere |

## Wire up the lead form

Open `assets/main.js` and set `FORM_ENDPOINT` to a form backend URL, such as Formspree, Netlify Forms, Basin, or a CRM webhook. The form POSTs JSON with these fields: name, phone, email, city, type, timing, and message. As a fallback, add `data-lead-email="you@domain.com"` to `<body>` and the form opens the visitor's email app instead. With neither set, the form tells visitors to call. That's safe, but it doesn't capture leads.

## Replace the line-art project cards with real photos

The "Our work" cards use blueprint-style SVG art so the site never shows fake projects. Real before-and-after photos of actual jobs will convert far better than anything else on the page. To swap one in, replace the `<svg>` inside a `.project-art` with `<img src="..." alt="..." loading="lazy" style="width:100%;height:100%;object-fit:cover">`.

## What's built in

**Mobile:**
- Every tap target is 48–54px.
- A sticky Call / Free walkthrough bar appears after the first scroll.
- Hero CTAs go full-width.
- Project filters scroll horizontally.
- Inputs use 16px font, which stops iOS from zooming on focus.
- The layout respects safe areas.
- Tested with no horizontal overflow at iPhone 13 width.

**Speed:**
- No frameworks or images.
- The only external request is Google Fonts, with `display=swap`.
- The whole site, CSS and JS included, is under 100 KB.
- Animations respect `prefers-reduced-motion`.

**SEO:**
- Per-page titles and descriptions, canonical URLs, Open Graph tags, and `GeneralContractor` schema.org markup.
