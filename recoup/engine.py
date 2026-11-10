"""Deterministic tax engine. The model never touches a dollar figure.

Given a line, its agreed category and the state profile, compute what tax should
have been paid and compare it with what was paid (vendor tax + self-accrued use tax).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .models import APLine, Category, Classification, Finding, Verdict
from .rules import StateProfile, profile_for

CONFIDENCE_FLOOR = 0.7


def _rate(line: APLine, prof: StateProfile) -> float:
    return line.local_rate if line.local_rate is not None else prof.default_rate


def _cutoff(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # Feb 29
        return today.replace(year=today.year - years, day=28)


def agreed_category(c: Classification, r: Classification | None) -> tuple[Category, list[str]]:
    """Both judges must agree with enough confidence, or the line goes to a human."""
    notes = []
    if c.category == Category.UNKNOWN:
        return Category.UNKNOWN, ["classifier could not decide"]
    if c.confidence < CONFIDENCE_FLOOR:
        notes.append(f"classifier confidence {c.confidence:.2f} below {CONFIDENCE_FLOOR}")
        return Category.UNKNOWN, notes
    if r is None:
        return c.category, ["no independent review"]
    if r.category != c.category:
        notes.append(f"reviewer disagreed: {r.category.value}")
        return Category.UNKNOWN, notes
    return c.category, notes


def evaluate(lines: list[APLine], cls: dict[str, Classification],
             rev: dict[str, Classification], today: date) -> list[Finding]:
    findings: list[Finding] = []
    agreed: dict[str, Category] = {}
    for ln in lines:
        agreed[ln.key], _ = agreed_category(cls[ln.key], rev.get(ln.key))

    # Freight follows the goods it ships: exempt only if every other line on the invoice is.
    invoice_cats: dict[tuple[str, str], set[Category]] = defaultdict(set)
    for ln in lines:
        if agreed[ln.key] != Category.FREIGHT:
            invoice_cats[(ln.vendor, ln.invoice_no)].add(agreed[ln.key])

    for ln in lines:
        c, r = cls[ln.key], rev.get(ln.key)
        cat, notes = agreed_category(c, r)
        f = Finding(line=ln, classification=c, review=r, verdict=Verdict.CORRECT, notes=notes)
        findings.append(f)

        prof = profile_for(ln.ship_to_state)
        if prof is None:
            f.verdict = Verdict.NEEDS_REVIEW
            f.notes.append(f"no rule profile for state {ln.ship_to_state}")
            continue
        f.rule_cite = prof.lookback_cite
        if ln.invoice_date < _cutoff(today, prof.lookback_years):
            f.verdict = Verdict.EXPIRED
            f.notes.append(f"invoice older than {prof.lookback_years}-year refund window")
            continue

        paid = ln.tax_charged + ln.use_tax_accrued
        rate = _rate(ln, prof)

        def fallback() -> bool:
            """Category-free rules for lines the judges could not settle."""
            if ln.tax_charged > 0 and ln.use_tax_accrued > 0:
                f.verdict, f.rule_id = Verdict.OVERPAID, "DUPLICATE_TAX"
                f.refund_amount = round(min(ln.tax_charged, ln.use_tax_accrued), 2)
                f.rule_cite = "Tax paid twice on the same purchase"
                f.refund_route = prof.accrued_route
                f.notes.append("category unresolved; only the duplicate portion is claimed")
                return True
            if ln.tax_charged > 0 and ln.tax_charged / ln.amount > prof.max_combined_rate + prof.rate_tolerance:
                f.verdict, f.rule_id = Verdict.OVERPAID, "RATE_ABOVE_MAX"
                f.refund_amount = round(ln.tax_charged - ln.amount * prof.max_combined_rate, 2)
                f.rule_cite = f"Combined rate capped at {prof.max_combined_rate:.4%} in {prof.name}"
                f.refund_route = prof.vendor_route
                f.notes.append("category unresolved; only the excess over the maximum rate is claimed")
                return True
            return False

        if cat == Category.UNKNOWN:
            if not fallback():
                f.verdict = Verdict.NEEDS_REVIEW
            continue

        rule = prof.categories[cat]
        f.rule_cite = rule.cite
        if rule.note:
            f.notes.append(rule.note)
        treatment = rule.treatment
        share = rule.taxable_share
        if treatment == "follows_invoice":
            others = invoice_cats.get((ln.vendor, ln.invoice_no), set())
            if others and all(prof.categories[o].treatment == "exempt" for o in others):
                treatment = "exempt"
                f.notes.append("freight on an invoice of exempt goods")
            elif others and all(prof.categories[o].treatment == "taxable" for o in others):
                treatment = "taxable"
            else:
                treatment = "review"
                f.notes.append("freight on mixed or undecided invoice")

        if treatment == "review":
            f.rule_id = f"REVIEW_{cat.value}"
            if not fallback():
                f.verdict = Verdict.NEEDS_REVIEW
            continue

        should_pay = 0.0 if treatment == "exempt" else round(ln.amount * share * rate, 2)
        delta = round(paid - should_pay, 2)
        if delta > 0.01:
            f.verdict, f.rule_id = Verdict.OVERPAID, f"{treatment.upper()}_{cat.value}"
            f.refund_amount = delta
            routes = ([prof.vendor_route] if ln.tax_charged > 0 else []) + \
                     ([prof.accrued_route] if ln.use_tax_accrued > 0 else [])
            f.refund_route = " AND ".join(routes)
            if ln.tax_charged > 0 and ln.use_tax_accrued > 0:
                f.notes.append("tax paid twice: vendor-billed and self-accrued")
            elif ln.tax_charged > 0 and treatment != "exempt" and ln.tax_charged / ln.amount > prof.max_combined_rate + prof.rate_tolerance:
                f.notes.append("billed rate above the legal maximum")
        elif delta < -0.01 and treatment != "exempt":
            f.verdict, f.rule_id = Verdict.UNDERPAID, f"USE_TAX_DUE_{cat.value}"
            f.exposure_amount = -delta
        else:
            f.rule_id = f"OK_{cat.value}"
    return findings
