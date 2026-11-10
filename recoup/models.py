"""Core data types. Everything the graph passes between nodes lives here."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum


class Category(str, Enum):
    """Closed taxonomy. The classifier must pick one; free text is never accepted."""

    MFG_EQUIPMENT = "MFG_EQUIPMENT"            # machinery that directly performs manufacturing
    MFG_CONSUMABLE = "MFG_CONSUMABLE"          # consumed in the process (cutting fluid, welding gas)
    COMPONENT = "COMPONENT"                    # becomes part of the finished product
    PACKAGING = "PACKAGING"                    # packaging that ships with the product to the customer
    RESALE = "RESALE"                          # bought to resell unchanged
    PROFESSIONAL_SERVICE = "PROFESSIONAL_SERVICE"  # legal, accounting, consulting, engineering
    SAAS = "SAAS"                              # software as a service / data processing
    UTILITY = "UTILITY"                        # electricity, natural gas
    FREIGHT = "FREIGHT"                        # delivery charges billed on the invoice
    HAND_TOOL = "HAND_TOOL"
    INTRAPLANT_TRANSPORT = "INTRAPLANT_TRANSPORT"  # forklifts, pallet jacks, conveyors between steps
    REPAIR_PART = "REPAIR_PART"                # replacement parts for equipment
    OFFICE_ADMIN = "OFFICE_ADMIN"
    UNKNOWN = "UNKNOWN"


class Verdict(str, Enum):
    OVERPAID = "OVERPAID"          # refund opportunity
    UNDERPAID = "UNDERPAID"        # exposure: use tax likely owed
    CORRECT = "CORRECT"
    NEEDS_REVIEW = "NEEDS_REVIEW"  # a human must decide
    EXPIRED = "EXPIRED"            # outside the refund window


@dataclass
class APLine:
    """One accounts-payable line, normalized from the client's export."""

    row: int
    vendor: str
    invoice_no: str
    invoice_date: date
    description: str
    amount: float               # pre-tax line amount
    tax_charged: float          # sales tax billed by the vendor
    use_tax_accrued: float = 0.0  # use tax the company self-accrued on this line
    gl_account: str = ""
    ship_to_state: str = "TX"
    local_rate: float | None = None  # combined state+local rate at ship-to, if known

    @property
    def key(self) -> str:
        """Stable id so a resumed run never re-pays for work already done."""
        raw = f"{self.vendor}|{self.invoice_no}|{self.row}|{self.description}|{self.amount}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["invoice_date"] = self.invoice_date.isoformat()
        return d


@dataclass
class Classification:
    category: Category
    confidence: float
    rationale: str
    source: str  # "heuristic", "claude:<model>", "gl-map"


@dataclass
class Finding:
    line: APLine
    classification: Classification
    review: Classification | None
    verdict: Verdict
    refund_amount: float = 0.0
    exposure_amount: float = 0.0
    rule_id: str = ""
    rule_cite: str = ""
    refund_route: str = ""
    notes: list[str] = field(default_factory=list)
    gate_failures: list[str] = field(default_factory=list)

    @property
    def claimable(self) -> bool:
        return self.verdict == Verdict.OVERPAID and not self.gate_failures

    def to_row(self) -> dict:
        return {
            "row": self.line.row,
            "vendor": self.line.vendor,
            "invoice_no": self.line.invoice_no,
            "invoice_date": self.line.invoice_date.isoformat(),
            "description": self.line.description,
            "amount": round(self.line.amount, 2),
            "tax_charged": round(self.line.tax_charged, 2),
            "use_tax_accrued": round(self.line.use_tax_accrued, 2),
            "category": self.classification.category.value,
            "confidence": round(self.classification.confidence, 2),
            "reviewer_category": self.review.category.value if self.review else "",
            "verdict": self.verdict.value,
            "refund_amount": round(self.refund_amount, 2),
            "exposure_amount": round(self.exposure_amount, 2),
            "rule_id": self.rule_id,
            "rule_cite": self.rule_cite,
            "refund_route": self.refund_route,
            "gate_failures": "; ".join(self.gate_failures),
            "notes": "; ".join(self.notes),
        }
