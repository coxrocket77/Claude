"""Evals and the improvement loop.

`score` measures a classifier against labeled lines. The metric punishes the
error that hurts clients: calling a taxable purchase exempt (a refund that gets
reversed in audit, with interest) counts three times as much as any other miss.

`tune` is an agent in a loop, in the spirit of autoresearch: a proposer model
reads the classifier's mistakes on a training split, writes playbook lessons,
and the loop keeps a lesson set only if the held-out score improves. The
playbook file is the only thing the loop may change.
"""
from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .classify import Classifier, ClaudeClassifier
from .models import APLine, Category
from .rules import TX

UNSAFE_WEIGHT = 3.0


@dataclass
class Labeled:
    line: APLine
    expected: Category


@dataclass
class Score:
    n: int
    correct: int
    unsafe: int
    abstained: int
    errors: list[dict]

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0

    @property
    def value(self) -> float:
        """Higher is better. Abstaining (UNKNOWN) is a miss but never unsafe."""
        if not self.n:
            return 0.0
        return (self.correct - UNSAFE_WEIGHT * self.unsafe) / self.n

    def summary(self) -> str:
        return (f"n={self.n} accuracy={self.accuracy:.1%} unsafe={self.unsafe} "
                f"abstained={self.abstained} score={self.value:.3f}")


def load_labeled(path: Path) -> list[Labeled]:
    out = []
    with open(path, newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), start=2):
            ln = APLine(row=i, vendor=r.get("vendor", ""), invoice_no=f"EVAL-{i}",
                        invoice_date=date.today(), description=r["description"],
                        amount=float(r.get("amount") or 100), tax_charged=0.0,
                        gl_account=r.get("gl_account", ""))
            out.append(Labeled(ln, Category(r["expected"])))
    return out


def _treatment(cat: Category) -> str:
    return TX.categories[cat].treatment


def score(judge: Classifier, data: list[Labeled]) -> Score:
    preds = judge.classify([d.line for d in data])
    correct = unsafe = abstained = 0
    errors = []
    for d in data:
        p = preds[d.line.key].category
        if p == d.expected:
            correct += 1
            continue
        if p == Category.UNKNOWN:
            abstained += 1
        # Unsafe: predicted exempt when the truth is taxable or needs review.
        is_unsafe = _treatment(p) == "exempt" and _treatment(d.expected) != "exempt"
        unsafe += is_unsafe
        errors.append({"description": d.line.description, "gl": d.line.gl_account,
                       "expected": d.expected.value, "predicted": p.value, "unsafe": is_unsafe})
    return Score(len(data), correct, unsafe, abstained, errors)


PROPOSE_SYSTEM = """You improve a tax classifier by writing short lessons for its playbook.
You will see the current playbook and the classifier's mistakes on training data.
Write at most 5 lessons. Each lesson is one line, general enough to apply to unseen items, and names the distinguishing feature (for example: "Forklift attachments and forks are INTRAPLANT_TRANSPORT, not REPAIR_PART").
Never write a lesson that pushes items toward an exempt category without a concrete distinguishing feature; false exemptions are the costliest error.
Return only the full revised playbook as a markdown bullet list. Keep useful old lessons."""


def tune(client, data: list[Labeled], playbook: Path, model: str, classifier_model: str,
         iterations: int = 3, holdout: float = 0.4, seed: int = 7, log=print) -> Path:
    rng = random.Random(seed)
    shuffled = data[:]
    rng.shuffle(shuffled)
    cut = int(len(shuffled) * (1 - holdout))
    train, test = shuffled[:cut], shuffled[cut:]
    tune_log = playbook.with_name("tune_log.md")

    def judge(pb: Path) -> ClaudeClassifier:
        return ClaudeClassifier(client, classifier_model, playbook=pb, label="tune")

    best = score(judge(playbook), test)
    log(f"baseline holdout: {best.summary()}")
    for it in range(1, iterations + 1):
        train_score = score(judge(playbook), train)
        if not train_score.errors:
            log("no training errors left; stopping")
            break
        current = playbook.read_text() if playbook.exists() else ""
        resp = client.messages.create(
            model=model, max_tokens=2000, system=PROPOSE_SYSTEM,
            messages=[{"role": "user", "content":
                       f"<playbook>\n{current or '(empty)'}\n</playbook>\n"
                       f"<mistakes>\n{json.dumps(train_score.errors, indent=1)}\n</mistakes>"}])
        candidate_text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        candidate = playbook.with_suffix(".candidate.md")
        candidate.write_text(candidate_text + "\n")
        cand = score(judge(candidate), test)
        kept = cand.value > best.value
        log(f"iter {it}: candidate holdout {cand.summary()} -> {'KEEP' if kept else 'discard'}")
        with open(tune_log, "a") as fh:
            fh.write(f"## iter {it} {'KEEP' if kept else 'discard'}\n"
                     f"- before: {best.summary()}\n- after: {cand.summary()}\n\n{candidate_text}\n\n")
        if kept:
            candidate.replace(playbook)
            best = cand
        else:
            candidate.unlink()
    return playbook
