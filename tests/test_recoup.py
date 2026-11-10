import asyncio
import csv
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from recoup import cli
from recoup.classify import ClaudeClassifier, GLReviewer, HeuristicClassifier
from recoup.engine import evaluate
from recoup.evals import load_labeled, score, tune
from recoup.gates import line_gates, run_gate
from recoup.graph import RunContext, run
from recoup.ingest import load_ap_csv
from recoup.models import APLine, Category, Classification, Verdict

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 9)


def line(desc, amount=1000.0, tax=82.5, use=0.0, d="2025-01-01", inv="I1", vendor="V", gl=""):
    return APLine(row=2, vendor=vendor, invoice_no=inv, invoice_date=date.fromisoformat(d),
                  description=desc, amount=amount, tax_charged=tax, use_tax_accrued=use, gl_account=gl)


def judged(lines, cat, rev_cat=None, conf=0.9):
    c = {ln.key: Classification(cat, conf, "t", "t") for ln in lines}
    r = {ln.key: Classification(rev_cat or cat, 0.9, "t", "r") for ln in lines}
    return c, r


def one(ln, cat, **kw):
    c, r = judged([ln], cat, **kw)
    return evaluate([ln], c, r, TODAY)[0]


# ---------- ingest ----------

def test_ingest_aliases_and_bad_rows(tmp_path):
    p = tmp_path / "ap.csv"
    p.write_text("Supplier,Invoice Number,Posting Date,Memo,Net Amount,Tax Amount,GL\n"
                 "Acme,A1,03/14/2025,Steel bar,\"$1,000.00\",$82.50,5010\n"
                 "Acme,A2,not a date,Steel,100,8,5010\n"
                 "Acme,A3,2025-03-14,Credit,(50.00),0,5010\n")
    res = load_ap_csv(p)
    assert len(res.lines) == 1 and res.lines[0].amount == 1000.0
    assert res.lines[0].invoice_date == date(2025, 3, 14)
    assert any("Row 3" in e for e in res.errors) and any("Row 4" in e for e in res.errors)


def test_ingest_missing_columns(tmp_path):
    p = tmp_path / "ap.csv"
    p.write_text("foo,bar\n1,2\n")
    res = load_ap_csv(p)
    assert not res.lines and "Missing required columns" in res.errors[0]


# ---------- engine ----------

def test_exempt_equipment_full_refund():
    f = one(line("CNC mill"), Category.MFG_EQUIPMENT)
    assert f.verdict == Verdict.OVERPAID and f.refund_amount == 82.5


def test_saas_partial_refund_is_twenty_percent():
    f = one(line("ERP SaaS", amount=10000, tax=825), Category.SAAS)
    assert f.verdict == Verdict.OVERPAID and f.refund_amount == pytest.approx(165.0)


def test_taxable_untaxed_is_exposure():
    f = one(line("forklift", amount=10000, tax=0), Category.INTRAPLANT_TRANSPORT)
    assert f.verdict == Verdict.UNDERPAID and f.exposure_amount == pytest.approx(825.0)


def test_exempt_with_vendor_and_use_tax_refunds_both():
    f = one(line("argon", tax=82.5, use=82.5), Category.MFG_CONSUMABLE)
    assert f.refund_amount == 165.0 and "AND" in f.refund_route


def test_duplicate_fallback_when_category_unresolved():
    f = one(line("misc", tax=82.5, use=82.5), Category.MFG_CONSUMABLE, rev_cat=Category.OFFICE_ADMIN)
    assert f.rule_id == "DUPLICATE_TAX" and f.refund_amount == 82.5


def test_rate_above_max_on_taxable():
    f = one(line("paper", amount=1000, tax=95), Category.OFFICE_ADMIN)
    assert f.verdict == Verdict.OVERPAID and f.refund_amount == pytest.approx(12.5)


def test_disagreement_and_low_confidence_go_to_review():
    assert one(line("x"), Category.MFG_EQUIPMENT, rev_cat=Category.HAND_TOOL).verdict == Verdict.NEEDS_REVIEW
    assert one(line("x"), Category.MFG_EQUIPMENT, conf=0.5).verdict == Verdict.NEEDS_REVIEW


def test_expired_outside_window():
    assert one(line("CNC", d="2022-11-08"), Category.MFG_EQUIPMENT).verdict == Verdict.EXPIRED
    assert one(line("CNC", d="2022-11-10"), Category.MFG_EQUIPMENT).verdict == Verdict.OVERPAID


def test_freight_follows_invoice():
    goods, fr = line("steel", inv="A"), line("freight", inv="A", amount=100, tax=8.25)
    fr.row = 3
    c = {goods.key: Classification(Category.COMPONENT, .9, "", ""), fr.key: Classification(Category.FREIGHT, .9, "", "")}
    out = evaluate([goods, fr], c, c, TODAY)
    assert out[1].verdict == Verdict.OVERPAID and out[1].refund_amount == 8.25

    tool = line("wrench", inv="B")
    fr2 = line("freight", inv="B", amount=100, tax=8.25)
    fr2.row = 4
    c2 = {tool.key: Classification(Category.HAND_TOOL, .9, "", ""), fr2.key: Classification(Category.FREIGHT, .9, "", "")}
    out2 = evaluate([tool, fr2], c2, c2, TODAY)
    assert out2[1].verdict == Verdict.CORRECT


def test_unknown_state_needs_review():
    ln = line("CNC")
    ln.ship_to_state = "ZZ"
    assert one(ln, Category.MFG_EQUIPMENT).verdict == Verdict.NEEDS_REVIEW


# ---------- gates ----------

def test_materiality_gate_strips_small_vendor():
    f = one(line("insert", amount=200, tax=16.5), Category.MFG_CONSUMABLE)
    line_gates([f])
    assert not f.claimable and "MATERIALITY" in f.gate_failures[0]


def test_exposure_gate_blocks_and_ack_releases():
    big_refund = one(line("CNC", amount=10000, tax=825, vendor="A"), Category.MFG_EQUIPMENT)
    exposure = one(line("forklift", amount=40000, tax=0, vendor="B", inv="X"), Category.INTRAPLANT_TRANSPORT)
    fs = [big_refund, exposure]
    line_gates(fs)
    assert run_gate(fs).blocked
    rep = run_gate(fs, ack_exposure=True)
    assert not rep.blocked and rep.net == pytest.approx(825 - 3300)


def test_no_claim_blocks():
    assert run_gate([]).blocked


# ---------- harness / graph ----------

class CountingJudge:
    def __init__(self, inner):
        self.inner, self.calls = inner, 0
        self.name = "counting"

    def classify(self, lines):
        self.calls += len(lines)
        return self.inner.classify(lines)


def test_end_to_end_and_resume(tmp_path):
    clf, rev = CountingJudge(HeuristicClassifier()), CountingJudge(GLReviewer())
    ctx = RunContext(ROOT / "sample/ap_export.csv", tmp_path / "run", "Test Co", clf, rev,
                     today=TODAY, log=lambda m: None)
    findings, gate, paths = run(ctx)
    assert not gate.blocked and gate.total_refund > 12000
    assert clf.calls == 21 and rev.calls == 21
    assert (tmp_path / "run/packet/vendor_letters/haas-automation-dealer.md").exists()
    assert "DRAFT, NOT APPROVED" in paths["report"].read_text()

    # Second run: every judgment is cached, zero new calls.
    clf2, rev2 = CountingJudge(HeuristicClassifier()), CountingJudge(GLReviewer())
    ctx2 = RunContext(ctx.ap_csv, ctx.run_dir, "Test Co", clf2, rev2, today=TODAY, log=lambda m: None)
    _, gate2, _ = run(ctx2)
    assert clf2.calls == 0 and rev2.calls == 0 and gate2.total_refund == gate.total_refund


def test_approve_stamps_packet_and_refuses_blocked(tmp_path):
    out = tmp_path / "run"
    assert cli.main(["run", str(ROOT / "sample/ap_export.csv"), "--client", "T", "--out", str(out),
                     "--offline", "--as-of", "2026-11-09"]) == 0
    assert cli.main(["approve", str(out), "--by", "Jane Doe, CPA"]) == 0
    cli.main(["run", str(ROOT / "sample/ap_export.csv"), "--client", "T", "--out", str(out),
              "--offline", "--as-of", "2026-11-09"])
    assert "APPROVED by Jane Doe, CPA" in (out / "packet/report.md").read_text()

    state = json.loads((out / "state.json").read_text())
    state["nodes"]["gate"]["blocked"] = True
    (out / "state.json").write_text(json.dumps(state))
    assert cli.main(["approve", str(out), "--by", "X"]) == 1


# ---------- Claude classifier with a fake client ----------

class FakeMessages:
    def __init__(self, responder):
        self.responder, self.calls = responder, []

    def create(self, **kw):
        self.calls.append(kw)
        return self.responder(kw)


def fake_client(responder):
    return SimpleNamespace(messages=FakeMessages(responder))


def tool_reply(items):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"items": items})])


def test_claude_classifier_parses_and_fills_gaps():
    lines = [line("CNC mill"), line("mystery")]
    lines[1].row = 3

    def responder(kw):
        assert kw["tool_choice"]["name"] == "record_classifications"
        ids = [json.loads(kw["messages"][0]["content"].split("<lines>\n")[1].split("\n</lines>")[0])[0]["id"]]
        return tool_reply([{"id": ids[0], "category": "MFG_EQUIPMENT", "confidence": 0.95, "rationale": "cnc"},
                           {"id": "bogus", "category": "NOT_A_CATEGORY", "confidence": 1, "rationale": ""}])

    clf = ClaudeClassifier(fake_client(responder), "m", batch_size=10)
    out = clf.classify(lines)
    assert out[lines[0].key].category == Category.MFG_EQUIPMENT
    assert out[lines[1].key].category == Category.UNKNOWN  # omitted line never vanishes


def test_reviewer_sees_gl_classifier_does_not():
    seen = {}

    def responder(kw):
        seen.setdefault("payloads", []).append(kw["messages"][0]["content"])
        return tool_reply([])

    ClaudeClassifier(fake_client(responder), "m").classify([line("x", gl="5010")])
    ClaudeClassifier(fake_client(responder), "m", include_gl=True).classify([line("x", gl="5010")])
    assert "gl_account" not in seen["payloads"][0] and "gl_account" in seen["payloads"][1]


# ---------- evals and the tune loop ----------

def test_eval_flags_unsafe_errors():
    data = load_labeled(ROOT / "evals/labeled.csv")

    class AlwaysExempt:
        def classify(self, lines):
            return {ln.key: Classification(Category.MFG_EQUIPMENT, 1, "", "") for ln in lines}

    s = score(AlwaysExempt(), data)
    assert s.unsafe > 0 and s.value < s.accuracy


def test_tune_keeps_only_improvements(tmp_path):
    data = load_labeled(ROOT / "evals/labeled.csv")
    truth = {d.line.description: d.expected.value for d in data}
    pb = tmp_path / "playbook.md"
    pb.write_text("")
    rounds = {"n": 0}

    def responder(kw):
        if "tools" in kw:  # classification call
            items = json.loads(kw["messages"][0]["content"].split("<lines>\n")[1].split("\n</lines>")[0])
            good = "LESSON-GOOD" in kw["system"]
            return tool_reply([{"id": it["id"],
                                "category": truth[it["description"]] if good else "UNKNOWN",
                                "confidence": 0.9, "rationale": ""} for it in items])
        rounds["n"] += 1  # proposer call: first proposal is useless, second is good
        text = "- LESSON-BAD" if rounds["n"] == 1 else "- LESSON-GOOD"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    tune(fake_client(responder), data, pb, "p", "c", iterations=3, log=lambda m: None)
    assert "LESSON-GOOD" in pb.read_text()
    log = (tmp_path / "tune_log.md").read_text()
    assert "iter 1 discard" in log and "iter 2 KEEP" in log


# ---------- MCP server ----------

def test_mcp_tools_listed_and_callable(tmp_path):
    from recoup.mcp_server import server
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"recoup_scan_ledger", "recoup_review_queue", "recoup_get_finding"}
    res = asyncio.run(server.call_tool("recoup_scan_ledger", {
        "ap_csv_path": str(ROOT / "sample/ap_export.csv"), "client_name": "T",
        "run_dir": str(tmp_path / "m"), "offline": True}))
    text = json.dumps(res, default=str)
    assert "refund_total" in text
