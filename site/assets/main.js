// Extreme Construction & Rehab: interactions (no dependencies)
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  // Lead routing. Set FORM_ENDPOINT to a form backend (Formspree, Netlify Forms, Basin, CRM webhook)
  // to receive leads by POST. Set data-lead-email on <body> to fall back to the visitor's email app.
  // With neither set, the form directs visitors to call.
  const FORM_ENDPOINT = "";
  const LEAD_EMAIL = document.body.dataset.leadEmail || "";
  const PHONE_HTML = '<a href="tel:+12145595799" style="text-decoration:underline">(214) 559-5799</a>';

  // Years in business, computed so the number never goes stale
  const years = new Date().getFullYear() - 1991;
  $$("[data-since]").forEach(el => {
    if (el.hasAttribute("data-count")) el.dataset.count = years;
    else el.textContent = years;
  });
  $$("[data-year]").forEach(el => (el.textContent = new Date().getFullYear()));

  // Header state + mobile call bar
  const header = $(".header");
  const bar = $(".mobile-bar");
  const onScroll = () => {
    const y = window.scrollY;
    if (header) header.classList.toggle("scrolled", y > 20);
    if (bar) bar.classList.toggle("show", y > 480);
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  // Mobile menu
  const menuBtn = $(".menu-btn");
  if (menuBtn) {
    const close = () => {
      document.body.classList.remove("menu-open");
      menuBtn.setAttribute("aria-expanded", "false");
    };
    menuBtn.addEventListener("click", () => {
      const open = document.body.classList.toggle("menu-open");
      menuBtn.setAttribute("aria-expanded", String(open));
    });
    $$(".nav-links a").forEach(a => a.addEventListener("click", close));
    document.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
  }

  const hasIO = "IntersectionObserver" in window;

  // Scroll reveal
  if (hasIO) {
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    $$(".reveal").forEach(el => io.observe(el));
  } else {
    $$(".reveal").forEach(el => el.classList.add("in"));
  }

  // Count-up stats
  const finalText = el => el.dataset.count + (el.dataset.suffix || "");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (hasIO && !reduced) {
    const countIO = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (!e.isIntersecting) return;
        const el = e.target, end = +el.dataset.count, suffix = el.dataset.suffix || "";
        const start = performance.now(), dur = 1400;
        const tick = t => {
          const p = Math.min((t - start) / dur, 1), eased = 1 - Math.pow(1 - p, 3);
          el.textContent = Math.round(end * eased) + suffix;
          if (p < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
        countIO.unobserve(el);
      });
    }, { threshold: 0.6 });
    $$("[data-count]").forEach(el => countIO.observe(el));
  } else {
    $$("[data-count]").forEach(el => (el.textContent = finalText(el)));
  }

  // Single-select chip groups
  $$("[data-chips]").forEach(group => {
    group.addEventListener("click", e => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      $$(".chip", group).forEach(c => c.setAttribute("aria-pressed", String(c === chip)));
      group.dispatchEvent(new CustomEvent("chipchange", { detail: chip.dataset.value }));
    });
  });

  // Hero project scoper: carries the visitor's choices into the quote form
  const scoper = $("#scoper");
  if (scoper) {
    const state = { type: "", timing: "" };
    $$("[data-chips]", scoper).forEach(g =>
      g.addEventListener("chipchange", e => { state[g.dataset.chips] = e.detail; })
    );
    const go = $("#scoper-go", scoper);
    if (go) go.addEventListener("click", () => {
      const type = $("#f-type"), timing = $("#f-timing");
      if (type && state.type) type.value = state.type;
      if (timing && state.timing) timing.value = state.timing;
      setTimeout(() => { const n = $("#f-name"); if (n) n.focus({ preventScroll: true }); }, 700);
    });
  }

  // Work filter
  const filter = $("#work-filter");
  if (filter) {
    filter.addEventListener("chipchange", e => {
      const v = e.detail;
      $$(".project").forEach(p => p.classList.toggle("hide", v !== "all" && p.dataset.cat !== v));
    });
  }

  // Quote form
  const form = $("form.quote");
  if (form) {
    const status = $(".form-status", form);
    const btn = $("button[type=submit]", form);
    const label = btn.textContent;
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(form));
      if (!data.name || !data.phone) {
        status.textContent = "Add your name and phone so we can reach you.";
        status.classList.add("show");
        return;
      }
      btn.disabled = true;
      btn.textContent = "Sending…";
      try {
        if (FORM_ENDPOINT) {
          const r = await fetch(FORM_ENDPOINT, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify(data)
          });
          if (!r.ok) throw new Error("Bad status " + r.status);
          status.textContent = "Got it. We'll call you within one business day to schedule your walkthrough.";
          form.reset();
        } else if (LEAD_EMAIL) {
          const body = Object.entries(data).map(([k, v]) => `${k}: ${v}`).join("\n");
          location.href = `mailto:${LEAD_EMAIL}?subject=${encodeURIComponent("Walkthrough request: " + (data.type || "project"))}&body=${encodeURIComponent(body)}`;
          status.innerHTML = "Your email app should open with your request filled in. Prefer to talk? Call " + PHONE_HTML + ".";
        } else {
          status.innerHTML = "The fastest way to book is a two-minute call: " + PHONE_HTML + ". We answer weekdays.";
        }
      } catch (err) {
        status.innerHTML = "That didn't go through. Call us at " + PHONE_HTML + " and we'll book you on the spot.";
      }
      status.classList.add("show");
      btn.disabled = false;
      btn.textContent = label;
    });
  }
})();
