"""State rule profiles.

Rules are data, not prompts. The model classifies a purchase into the closed
taxonomy; deterministic code decides what that means for tax. That split keeps
the dollar math auditable and keeps the model out of the arithmetic.

Citations are starting points for a licensed preparer. Every packet ships with a
"verify before filing" notice, and the gate refuses to mark a packet ready
without a named human approver.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Category


@dataclass(frozen=True)
class CategoryRule:
    treatment: str  # "exempt" | "taxable" | "partial" | "follows_invoice" | "review"
    cite: str
    taxable_share: float = 1.0  # for "partial": share of the price that is taxable
    note: str = ""


@dataclass(frozen=True)
class StateProfile:
    code: str
    name: str
    max_combined_rate: float
    default_rate: float          # used for exposure estimates when the line has no rate
    lookback_years: int
    lookback_cite: str
    rate_tolerance: float = 0.0005
    categories: dict[Category, CategoryRule] = field(default_factory=dict)
    vendor_route: str = ""
    accrued_route: str = ""


TX = StateProfile(
    code="TX",
    name="Texas",
    max_combined_rate=0.0825,
    default_rate=0.0825,
    lookback_years=4,
    lookback_cite="Tex. Tax Code §111.104, §111.201 (4-year limitation)",
    categories={
        Category.MFG_EQUIPMENT: CategoryRule(
            "exempt", "Tex. Tax Code §151.318; 34 TAC §3.300",
            note="Must directly cause a physical or chemical change in the product."),
        Category.MFG_CONSUMABLE: CategoryRule(
            "exempt", "Tex. Tax Code §151.318; 34 TAC §3.300",
            note="Necessary and essential, consumed in the manufacturing process."),
        Category.COMPONENT: CategoryRule("exempt", "Tex. Tax Code §151.318(a)(1)"),
        Category.PACKAGING: CategoryRule("exempt", "Tex. Tax Code §151.302; 34 TAC §3.314"),
        Category.RESALE: CategoryRule("exempt", "Tex. Tax Code §151.302 (resale certificate)"),
        Category.PROFESSIONAL_SERVICE: CategoryRule(
            "exempt", "Not an enumerated taxable service, Tex. Tax Code §151.0101"),
        Category.SAAS: CategoryRule(
            "partial", "Tex. Tax Code §151.351 (20% of data processing exempt)", taxable_share=0.80),
        Category.UTILITY: CategoryRule(
            "review", "Tex. Tax Code §151.317; 34 TAC §3.295",
            note="Exempt only with a predominant-use study showing >50% manufacturing use."),
        Category.FREIGHT: CategoryRule(
            "follows_invoice", "Tex. Tax Code §151.007 (delivery charges follow the item)"),
        Category.HAND_TOOL: CategoryRule("taxable", "Excluded by Tex. Tax Code §151.318(c)"),
        Category.INTRAPLANT_TRANSPORT: CategoryRule(
            "taxable", "Excluded by Tex. Tax Code §151.318(c)"),
        Category.REPAIR_PART: CategoryRule(
            "review", "Tex. Tax Code §151.318; 34 TAC §3.300",
            note="Exempt if a replacement part for exempt equipment with useful life > 6 months."),
        Category.OFFICE_ADMIN: CategoryRule("taxable", "Tex. Tax Code §151.051"),
        Category.UNKNOWN: CategoryRule("review", ""),
    },
    vendor_route=("Ask the vendor for a refund, or get a signed Assignment of Right to Refund "
                  "(Form 00-985) and file a Claim for Refund (Form 00-957) with the Comptroller"),
    accrued_route="File a Claim for Refund (Form 00-957) with the Comptroller for self-accrued use tax",
)

PROFILES: dict[str, StateProfile] = {"TX": TX}

EXEMPT_LIKE = {"exempt"}


def profile_for(state: str) -> StateProfile | None:
    return PROFILES.get(state.upper().strip())
