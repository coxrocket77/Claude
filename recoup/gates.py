"""Gates: deterministic checks that can say no.

Line gates strip weak findings out of a claim. Run gates block the whole packet.
Nothing in this module calls a model, so a model cannot argue its way past it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .models import Finding, Verdict

MIN_VENDOR_CLAIM = 50.00      # below this, a vendor refund request costs more than it returns
EXPOSURE_RATIO_BLOCK = 0.25   # filing invites an audit; block if exposure is this large vs refunds


@dataclass
class GateReport:
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)
    total_refund: float = 0.0
    total_exposure: float = 0.0
    net: float = 0.0


def line_gates(findings: list[Finding]) -> None:
    for f in findings:
        if f.verdict != Verdict.OVERPAID:
            continue
        ln = f.line
        if not (ln.vendor and ln.invoice_no and ln.invoice_date):
            f.gate_failures.append("EVIDENCE: missing vendor, invoice number or date")
        if f.rule_id not in ("DUPLICATE_TAX", "RATE_ABOVE_MAX") and f.review is None:
            f.gate_failures.append("REVIEW: no independent review of the category")
        if f.refund_amount <= 0:
            f.gate_failures.append("AMOUNT: non-positive refund")
        if f.refund_amount > ln.tax_charged + ln.use_tax_accrued + 0.01:
            f.gate_failures.append("AMOUNT: refund exceeds tax actually paid")

    # Materiality is per vendor, after line gates.
    by_vendor: dict[str, float] = defaultdict(float)
    for f in findings:
        if f.claimable:
            by_vendor[f.line.vendor] += f.refund_amount
    for f in findings:
        if f.claimable and by_vendor[f.line.vendor] < MIN_VENDOR_CLAIM:
            f.gate_failures.append(
                f"MATERIALITY: vendor total ${by_vendor[f.line.vendor]:.2f} under ${MIN_VENDOR_CLAIM:.0f}")


def run_gate(findings: list[Finding], ack_exposure: bool = False) -> GateReport:
    rep = GateReport()
    rep.total_refund = round(sum(f.refund_amount for f in findings if f.claimable), 2)
    rep.total_exposure = round(sum(f.exposure_amount for f in findings
                                   if f.verdict == Verdict.UNDERPAID), 2)
    rep.net = round(rep.total_refund - rep.total_exposure, 2)
    if rep.total_refund <= 0:
        rep.blocked = True
        rep.reasons.append("NO_CLAIM: no findings passed the line gates")
    elif rep.total_exposure > EXPOSURE_RATIO_BLOCK * rep.total_refund and not ack_exposure:
        rep.blocked = True
        rep.reasons.append(
            f"EXPOSURE: ${rep.total_exposure:,.2f} of likely use tax owed against "
            f"${rep.total_refund:,.2f} of refunds. A refund claim invites audit of the same "
            f"period. Re-run with --ack-exposure after the client decides how to handle it "
            f"(voluntary disclosure, offset, or narrowing the claim).")
    return rep
