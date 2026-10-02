"""Build the Finance workbook and the CSV outputs."""
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from .classify import classify_text, notes_mention_replacement, replacement_evidence
from .clean import REPLACEMENT_SHIPPING


def add_inference(df):
    r = df["refund_inr"].notna()
    out = df.copy()
    out["inferred_reason"] = ""
    out["evidence"] = ""
    res = out[r].apply(lambda x: classify_text(x["customer_message"], x["agent_notes"]), axis=1)
    out.loc[r, "inferred_reason"] = [a for a, _ in res]
    out.loc[r, "evidence"] = [b for _, b in res]
    out["replacement_in_notes"] = out["agent_notes"].map(notes_mention_replacement)
    out["refund_and_replacement"] = r & ((out["replacement_issued"] == "Y") | out["replacement_in_notes"])
    out["replacement_evidence"] = [replacement_evidence(n, f == "Y") if rf else ""
                                   for n, f, rf in zip(out["agent_notes"], out["replacement_issued"], r)]
    out["replacement_cost_inr"] = np.where(out["refund_and_replacement"], out["unit_cost_inr"] + REPLACEMENT_SHIPPING, 0)
    return out


def _pivot(refunds, row, col="month"):
    p = refunds.pivot_table(index=row, columns=col, values="refund_inr", aggfunc="sum", fill_value=0)
    return p.round(0)


def agent_summary(df):
    g = df.groupby("agent_id")
    s = g.agg(agent=("name", "first"), team=("agent_team", "first"), tier=("tier", "first"),
              site=("site", "first"), tickets=("ticket_id", "count"),
              refund_tickets=("refund_inr", "count"), refund_inr=("refund_inr", "sum"),
              gw_other_inr=("refund_inr", lambda x: x[df.loc[x.index, "refund_reason_code"] == "GW-OTHER"].sum()),
              refund_and_replacement=("refund_and_replacement", "sum"))
    s["refund_rate"] = s["refund_tickets"] / s["tickets"]
    s["avg_refund_inr"] = s["refund_inr"] / s["refund_tickets"].replace(0, np.nan)
    team_rate = s.groupby("team").apply(lambda x: x["refund_tickets"].sum() / x["tickets"].sum(), include_groups=False)
    s["team_refund_rate"] = s["team"].map(team_rate)
    s["rate_vs_team"] = s["refund_rate"] / s["team_refund_rate"]
    return s.sort_values("refund_inr", ascending=False).round(3).reset_index()


def build(df, bridge, out_dir):
    refunds = df[df["refund_inr"].notna()]
    months = sorted(df["month"].unique())

    sheets = {}
    sheets["Reconciliation"] = pd.DataFrame(bridge, columns=["Step", "Rs", "Refund tickets"])
    by_code = _pivot(refunds, "refund_reason_code").reindex(columns=months, fill_value=0)
    by_inf = _pivot(refunds, "inferred_reason").reindex(columns=months, fill_value=0)
    sheets["By reason code (agent)"] = by_code.reset_index().rename(columns={"refund_reason_code": "Reason code"})
    sheets["By reason (from text)"] = by_inf.reset_index().rename(columns={"inferred_reason": "Inferred reason"})
    sheets["Code vs text (GW-OTHER)"] = (refunds[refunds["refund_reason_code"] == "GW-OTHER"]
        .groupby("inferred_reason").agg(tickets=("ticket_id", "count"), refund_inr=("refund_inr", "sum"))
        .sort_values("refund_inr", ascending=False).round(0).reset_index())
    sheets["By agent"] = agent_summary(df)
    sheets["By agent x month"] = (_pivot(refunds, "agent_id").reindex(columns=months, fill_value=0)
                                  .reset_index().merge(df[["agent_id", "name", "agent_team"]].drop_duplicates("agent_id"), on="agent_id")
                                  [["agent_id", "name", "agent_team"] + months])
    both = refunds[refunds["refund_and_replacement"]]
    sheets["Refund + replacement"] = both[["ticket_id", "created_at", "month", "agent_id", "assigned_team", "product_name", "refund_inr",
                                           "replacement_issued", "replacement_in_notes", "replacement_cost_inr", "refund_reason_code"]]

    mt = df.groupby("month").agg(tickets=("ticket_id", "count"), refund_tickets=("refund_inr", "count"), refund_inr=("refund_inr", "sum")).reset_index()
    mt.insert(3, "refund_rate", None)
    mt["avg_refund_inr"] = None
    sheets["Monthly trend"] = mt
    strict = refunds["refund_and_replacement"] & (refunds["replacement_evidence"] != "notes, replacement only")
    q = refunds.assign(strict=strict).groupby("quarter").agg(
        refund_tickets=("ticket_id", "count"), refund_and_replacement_all=("refund_and_replacement", "sum"),
        of_which_strict=("strict", "sum"), refund_inr_on_these=("refund_inr", lambda x: x[refunds.loc[x.index, "refund_and_replacement"]].sum()),
        replacement_cost_inr=("replacement_cost_inr", "sum")).reset_index()
    sheets["Refund+repl by quarter"] = q
    try:
        from .validate import score
        _, v = score(refunds)
        sheets["Validation"] = pd.DataFrame([
            ("GW-OTHER sample size", v["n"]), ("Correct", v["correct"]), ("Accuracy", None), ("Error rate", None),
            ("95% CI low", round(v["ci_low"], 3)), ("95% CI high", round(v["ci_high"], 3)),
            ("NOTE", "Labels were assigned by Claude reading the ticket text after seeing the classifier output - NOT independent. Re-label blind (validate.py writes a blind sheet) before relying on this."),
        ], columns=["Measure", "Value"])
    except FileNotFoundError:
        pass
    sheets["Notes"] = pd.DataFrame([
        ("Amounts", "Legacy (legacy_fd) refund amounts divided by 100 (paise). Duplicate ticket_ids de-duplicated, helpdesk copy kept."),
        ("Month", "Ticket created_at as exported (IST). Tested: shifting by 5.5h would move only ~0.5% of refund value between months."),
        ("Reason (from text)", "Keyword rules on customer message + agent note. FAULT-DOA-WTY = product fault/wrong item; DOA vs warranty cannot be split (no delivery date)."),
        ("Refund + replacement", "replacement_issued=Y or agent note says a replacement went out. 'strict' excludes notes that only say 'replacement dispatched' without pairing it with the refund."),
        ("Agent view", "Association and workload context only. Rates are per refund ticket; Tier 2 is not comparable with Tier 1 on volume (policy s6)."),
        ("Pre-export caveat", "agent_id is the resolving agent, not necessarily who raised the refund."),
    ], columns=["Topic", "Note"])

    path = f"{out_dir}/refund_summary.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        for name, frame in sheets.items():
            frame.to_excel(w, sheet_name=name[:31], index=False)
    _format(path, months)
    df.to_csv(f"{out_dir}/tickets_clean.csv", index=False)
    refunds[["ticket_id", "month", "agent_id", "refund_reason_code", "inferred_reason", "evidence", "refund_inr",
             "customer_message", "agent_notes"]].to_csv(f"{out_dir}/refund_reasons.csv", index=False)
    return sheets


def _format(path, months):
    wb = load_workbook(path)
    font = Font(name="Arial", size=10)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                c.font = font
        for c in ws[1]:
            c.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F3864")
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for i, col in enumerate(ws.columns, 1):
            ws.column_dimensions[get_column_letter(i)].width = 44 if i == 1 and ws.title == "Reconciliation" else 14
        ws.freeze_panes = "B2"
    # Total row + column (live SUM formulas) on the two reason pivots and the agent x month pivot
    for title, first_num_col in (("By reason code (agent)", 2), ("By reason (from text)", 2), ("By agent x month", 4)):
        ws = wb[title]
        last_r, last_c = ws.max_row, ws.max_column
        ws.cell(1, last_c + 1, "Total").font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        ws.cell(1, last_c + 1).fill = PatternFill("solid", fgColor="1F3864")
        for r in range(2, last_r + 1):
            ws.cell(r, last_c + 1, f"=SUM({get_column_letter(first_num_col)}{r}:{get_column_letter(last_c)}{r})")
        ws.cell(last_r + 1, 1, "Total").font = Font(name="Arial", size=10, bold=True)
        for c in range(first_num_col, last_c + 2):
            L = get_column_letter(c)
            ws.cell(last_r + 1, c, f"=SUM({L}2:{L}{last_r})").font = Font(name="Arial", size=10, bold=True)
        for row in ws.iter_rows(min_row=2, min_col=first_num_col):
            for c in row:
                c.number_format = "#,##0"
    mt = wb["Monthly trend"]
    for r in range(2, mt.max_row + 1):
        mt.cell(r, 4, f"=IF(B{r}=0,0,C{r}/B{r})").number_format = "0.0%"
        mt.cell(r, 6, f"=IF(C{r}=0,0,E{r}/C{r})").number_format = "#,##0"
        mt.cell(r, 5).number_format = "#,##0"
    last = mt.max_row
    mt.cell(last + 1, 1, "Total").font = Font(name="Arial", size=10, bold=True)
    for c in (2, 3, 5):
        L = get_column_letter(c)
        mt.cell(last + 1, c, f"=SUM({L}2:{L}{last})").font = Font(name="Arial", size=10, bold=True)
        mt.cell(last + 1, c).number_format = "#,##0"
    mt.cell(last + 1, 4, f"=C{last+1}/B{last+1}").number_format = "0.0%"
    mt.cell(last + 1, 6, f"=E{last+1}/C{last+1}").number_format = "#,##0"
    if "Validation" in wb.sheetnames:
        v = wb["Validation"]
        v["B4"] = "=B3/B2"; v["B4"].number_format = "0.0%"
        v["B5"] = "=1-B4"; v["B5"].number_format = "0.0%"
        v.column_dimensions["B"].width = 90
        v["B8"].alignment = Alignment(wrap_text=True, vertical="top")
    n = wb["Notes"]; n.column_dimensions["A"].width = 22; n.column_dimensions["B"].width = 110
    for r in range(2, n.max_row + 1):
        n.cell(r, 2).alignment = Alignment(wrap_text=True, vertical="top")
    q = wb["Refund+repl by quarter"]
    for r in range(2, q.max_row + 1):
        for c in (5, 6):
            q.cell(r, c).number_format = "#,##0"
    for ws2 in (q,):
        ws2.column_dimensions["A"].width = 14
        for i in range(2, 7):
            ws2.column_dimensions[get_column_letter(i)].width = 22
    rec = wb["Reconciliation"]
    for r in range(2, rec.max_row + 1):
        rec.cell(r, 2).number_format = "#,##0;(#,##0)"
    wb.save(path)
