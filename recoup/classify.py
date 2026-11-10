"""Classifiers: put each AP line into the closed taxonomy.

Two independent judges, by design:
  * the classifier reads the description (Claude, or a keyword heuristic offline)
  * the reviewer reads from a different angle (Claude with an auditor's brief, or
    the GL account offline) and never sees the classifier's answer

The engine only trusts a category when both judges agree.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol

from .models import APLine, Category, Classification

TAXONOMY_DOC = {
    "MFG_EQUIPMENT": "Machinery that directly shapes, cuts, mixes or otherwise changes the product (CNC mill, lathe, press brake, injection molder, welder used on product).",
    "MFG_CONSUMABLE": "Consumed during production and essential to it (cutting fluid, coolant, welding gas, abrasives used on product, mold release).",
    "COMPONENT": "Raw material or part that becomes physically part of the finished product (steel bar, aluminum sheet, fasteners built into product, resin).",
    "PACKAGING": "Boxes, crates, labels or wrap that leave with the product to the customer.",
    "RESALE": "Goods bought to resell unchanged.",
    "PROFESSIONAL_SERVICE": "Legal, accounting, audit, consulting, engineering design, staffing advisory. Not janitorial, security or repair.",
    "SAAS": "Hosted software subscriptions, cloud platforms, data processing services.",
    "UTILITY": "Electricity or natural gas bills.",
    "FREIGHT": "Shipping, delivery or freight charges billed as their own line.",
    "HAND_TOOL": "Hand-held, non-powered or small powered tools (wrenches, calipers, drills, hand grinders).",
    "INTRAPLANT_TRANSPORT": "Moves material between steps or around the plant (forklift, pallet jack, hand truck, conveyor between stations).",
    "REPAIR_PART": "Replacement or repair parts for equipment (spindle motor, belts, bearings, hydraulic pump).",
    "OFFICE_ADMIN": "Office supplies, furniture, breakroom, IT hardware for staff, janitorial and cleaning supplies.",
    "UNKNOWN": "Not enough information to decide. Prefer this over guessing.",
}

# Ordered: earlier patterns win. Specific beats generic.
KEYWORDS: list[tuple[str, Category, float]] = [
    (r"\b(freight|shipping|delivery charge|delivery fee|ltl|fedex|ups ground)\b", Category.FREIGHT, 0.9),
    (r"\b(legal|attorney|audit fee|cpa|accounting|consulting|advisory|engineering design)\b", Category.PROFESSIONAL_SERVICE, 0.85),
    (r"\b(saas|subscription|cloud|hosted|software license|erp license|license renewal|platform fee)\b", Category.SAAS, 0.85),
    (r"\b(forklifts?|pallet jacks?|hand trucks?|conveyors?|order pickers?)\b", Category.INTRAPLANT_TRANSPORT, 0.85),
    (r"\b(electricity|electric service|kwh|natural gas|utility|utilities)\b", Category.UTILITY, 0.85),
    (r"\b(replacement|spindle motor|bearing|belt|hydraulic pump|repair kit|seal kit|rebuild)\b", Category.REPAIR_PART, 0.75),
    (r"\b(wrench|caliper|screwdriver|hammer|hand tool|cordless drill|angle grinder|socket set)\b", Category.HAND_TOOL, 0.8),
    (r"\b(cnc|lathe|mill(ing)? machine|press brake|injection mold(er|ing)|laser cutter|waterjet|machining center)\b", Category.MFG_EQUIPMENT, 0.85),
    (r"\b(coolant|cutting fluid|welding gas|argon|shielding gas|abrasive|mold release|end mill|carbide insert)\b", Category.MFG_CONSUMABLE, 0.75),
    (r"\b(steel|aluminum|bar stock|sheet metal|resin|raw material|plate stock|tubing)\b", Category.COMPONENT, 0.75),
    (r"\b(carton|corrugated|crate|shipping box|stretch wrap|product label)\b", Category.PACKAGING, 0.75),
    (r"\b(for resale|resale)\b", Category.RESALE, 0.8),
    (r"\b(paper|toner|desks?|chairs?|breakroom|coffee|janitorial|cleaning supplies|laptops?|monitors?)\b", Category.OFFICE_ADMIN, 0.8),
]

# Typical chart-of-accounts ranges. Clients map their own GL in config; this is the default.
GL_MAP: list[tuple[str, Category]] = [
    (r"^50[0-4]\d", Category.COMPONENT),
    (r"^505\d", Category.PACKAGING),
    (r"^51\d\d", Category.MFG_CONSUMABLE),
    (r"^15[0-4]\d", Category.MFG_EQUIPMENT),
    (r"^155\d", Category.INTRAPLANT_TRANSPORT),
    (r"^52\d\d", Category.FREIGHT),
    (r"^53\d\d", Category.REPAIR_PART),
    (r"^54\d\d", Category.HAND_TOOL),
    (r"^61\d\d", Category.OFFICE_ADMIN),
    (r"^62\d\d", Category.SAAS),
    (r"^63\d\d", Category.UTILITY),
    (r"^64\d\d", Category.PROFESSIONAL_SERVICE),
    (r"^40\d\d", Category.RESALE),
]


class Classifier(Protocol):
    def classify(self, lines: list[APLine]) -> dict[str, Classification]: ...


class HeuristicClassifier:
    name = "heuristic"

    def classify(self, lines: list[APLine]) -> dict[str, Classification]:
        out = {}
        for ln in lines:
            text = ln.description.lower()
            for pat, cat, conf in KEYWORDS:
                if re.search(pat, text):
                    out[ln.key] = Classification(cat, conf, f"keyword /{pat}/", self.name)
                    break
            else:
                out[ln.key] = Classification(Category.UNKNOWN, 0.0, "no keyword matched", self.name)
        return out


class GLReviewer:
    """Offline reviewer: judges from the GL account only, never from the description."""

    name = "gl-map"

    def __init__(self, gl_map: list[tuple[str, Category]] | None = None):
        self.gl_map = gl_map or GL_MAP

    def classify(self, lines: list[APLine]) -> dict[str, Classification]:
        out = {}
        for ln in lines:
            for pat, cat in self.gl_map:
                if ln.gl_account and re.search(pat, ln.gl_account):
                    out[ln.key] = Classification(cat, 0.8, f"GL {ln.gl_account}", self.name)
                    break
            else:
                out[ln.key] = Classification(Category.UNKNOWN, 0.0, "GL unmapped", self.name)
        return out


CLASSIFY_TOOL = {
    "name": "record_classifications",
    "description": "Record exactly one taxonomy category per AP line. Call once with every line in the batch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The line id exactly as given."},
                        "category": {"type": "string", "enum": [c.value for c in Category]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "rationale": {"type": "string", "description": "One sentence citing the words in the description that decided it."},
                    },
                    "required": ["id", "category", "confidence", "rationale"],
                },
            }
        },
        "required": ["items"],
    },
}

CLASSIFIER_SYSTEM = """You classify purchase lines from a manufacturer's accounts payable ledger into a fixed tax taxonomy.

<taxonomy>
{taxonomy}
</taxonomy>

<rules>
- Judge from what the item is and how a manufacturer would use it. Vendor names are weak evidence.
- Pick UNKNOWN with low confidence when the description is too vague. A wrong confident answer costs the client an audit adjustment; UNKNOWN costs a human two minutes.
- Confidence means the probability a state auditor would accept the category.
- You do not compute tax. Downstream code does.
</rules>

<playbook>
Lessons learned from past evaluation runs:
{playbook}
</playbook>"""

REVIEWER_SYSTEM = """You are a skeptical state sales tax auditor reviewing a refund claim. For each purchase line, decide which taxonomy category you would defend in an audit. Lean toward the taxable reading when the description supports both; refunds that rest on a generous reading get reversed.

<taxonomy>
{taxonomy}
</taxonomy>

Use the GL account as evidence alongside the description. Pick UNKNOWN when you would ask the taxpayer for more documentation."""


def _playbook_text(path: Path | None) -> str:
    if path and path.exists():
        return path.read_text().strip() or "(none yet)"
    return "(none yet)"


class ClaudeClassifier:
    """Batches lines, fans batches out in parallel, forces structured output via a tool."""

    def __init__(self, client, model: str, system_template: str = CLASSIFIER_SYSTEM,
                 batch_size: int = 25, workers: int = 4, playbook: Path | None = None,
                 include_gl: bool = False, label: str = "claude"):
        self.client, self.model = client, model
        self.system_template, self.batch_size, self.workers = system_template, batch_size, workers
        self.playbook, self.include_gl, self.label = playbook, include_gl, label

    def _system(self) -> str:
        tax = "\n".join(f"{k}: {v}" for k, v in TAXONOMY_DOC.items())
        return self.system_template.format(taxonomy=tax, playbook=_playbook_text(self.playbook))

    def _batch(self, batch: list[APLine]) -> dict[str, Classification]:
        payload = []
        for ln in batch:
            item = {"id": ln.key, "vendor": ln.vendor, "description": ln.description,
                    "amount": ln.amount}
            if self.include_gl:
                item["gl_account"] = ln.gl_account
            payload.append(item)
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self._system(),
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "record_classifications"},
            messages=[{"role": "user", "content":
                       "<lines>\n" + json.dumps(payload, indent=1) + "\n</lines>"}],
        )
        out: dict[str, Classification] = {}
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use":
                for it in block.input.get("items", []):
                    try:
                        cat = Category(it["category"])
                    except ValueError:
                        cat = Category.UNKNOWN
                    out[it["id"]] = Classification(
                        cat, float(it.get("confidence", 0)), it.get("rationale", ""),
                        f"{self.label}:{self.model}")
        # Any line the model skipped becomes UNKNOWN rather than silently disappearing.
        for ln in batch:
            out.setdefault(ln.key, Classification(Category.UNKNOWN, 0.0, "model omitted line",
                                                  f"{self.label}:{self.model}"))
        return out

    def classify(self, lines: list[APLine]) -> dict[str, Classification]:
        batches = [lines[i:i + self.batch_size] for i in range(0, len(lines), self.batch_size)]
        out: dict[str, Classification] = {}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for result in pool.map(self._batch, batches):
                out.update(result)
        return out
