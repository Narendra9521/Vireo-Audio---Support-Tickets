"""How do we know the classifier is right, and how often is it wrong?

python -m vireo_refunds.validate            # proxy agreement + replacement recall; writes a BLIND label sheet
python -m vireo_refunds.validate --score    # scores validation/labels.csv against the classifier

 1. PROXY AGREEMENT (not accuracy): tickets where the agent picked a specific code (not GW-OTHER) are
    treated as mostly-correct labels; we report how often the text rules agree. Agents mis-code too.
 2. REPLACEMENT DETECTOR: share of agent-flagged replacement_issued=Y refund tickets that the notes detector also finds.
 3. HAND-LABEL ACCURACY on GW-OTHER (the cases that matter): validation/labels.csv holds ticket_id + true_reason.
    The label sheet written for a human labeller (validation/label_sheet.csv, git-ignored because it contains
    customer text) does NOT show the classifier's prediction, so labelling is blind.
"""
import argparse, math, os
import pandas as pd

VALID = {"CANCEL", "DUP-PAYMENT", "PRICE-ADJ", "LOST-TRANSIT", "RETURN-QC-OK", "DOA-REPL", "WTY-BUYBACK", "FAULT-DOA-WTY", "OTHER"}
FAULT = ("DOA-REPL", "WTY-BUYBACK", "FAULT-DOA-WTY")


def hit(code, pred):
    """FAULT-DOA-WTY is a bucket that stands for DOA-REPL or WTY-BUYBACK (needs delivery date to split)."""
    return code in FAULT if pred == "FAULT-DOA-WTY" else code == pred


def wilson(k, n, z=1.96):
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


def score(df, labels_path="validation/labels.csv"):
    lab = pd.read_csv(labels_path)
    lab = lab[lab["true_reason"].isin(VALID)]
    m = lab.merge(df[["ticket_id", "inferred_reason", "refund_reason_code"]], on="ticket_id", how="left")
    m["ok"] = [hit(t, p) for t, p in zip(m["true_reason"], m["inferred_reason"])]
    k, n = int(m["ok"].sum()), len(m)
    lo, hi = wilson(k, n)
    return m, dict(n=n, correct=k, accuracy=k / n, error_rate=1 - k / n, ci_low=lo, ci_high=hi)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--labels", default="validation/labels.csv", help="csv with ticket_id,true_reason")
    a = ap.parse_args(argv)
    df = pd.read_csv(f"{a.out}/tickets_clean.csv")
    r = df[df["refund_inr"].notna()].copy()

    if a.score:
        m, s = score(r, a.labels)
        print(f"Hand-labelled GW-OTHER sample: n={s['n']}  correct={s['correct']}  accuracy={s['accuracy']:.1%}  "
              f"error rate={s['error_rate']:.1%}  95% CI for accuracy {s['ci_low']:.1%}-{s['ci_high']:.1%}")
        print("Failures (true -> predicted):")
        print(m[~m["ok"]][["ticket_id", "true_reason", "inferred_reason"]].to_string(index=False))
        # Review file: text + predicted + true + correct (git-ignored: contains customer text)
        txt = r[["ticket_id", "customer_message", "agent_notes"]]
        rev = m.merge(txt, on="ticket_id", how="left").rename(columns={"inferred_reason": "predicted_reason"})
        rev = rev[["ticket_id", "customer_message", "agent_notes", "predicted_reason", "true_reason", "ok"]].rename(columns={"ok": "correct"})
        os.makedirs("validation", exist_ok=True)
        name = "validation/label_review_" + os.path.splitext(os.path.basename(a.labels))[0] + ".csv"
        rev.to_csv(name, index=False)
        print(f"wrote {name} ({len(rev)} rows, git-ignored)")
        return

    ok = r[r["refund_reason_code"] != "GW-OTHER"].copy()
    ok["hit"] = [hit(c, p) for c, p in zip(ok["refund_reason_code"], ok["inferred_reason"])]
    print(f"1. PROXY agreement with agent-picked codes (NOT accuracy): n={len(ok)}  agreement={ok['hit'].mean():.1%}  "
          f"unclassified={(ok['inferred_reason'] == 'UNCLASSIFIED').mean():.1%}")
    print(ok[~ok["hit"]].groupby(["refund_reason_code", "inferred_reason"]).size().sort_values(ascending=False).head(5).to_string())
    y = r[r["replacement_issued"] == "Y"]
    print(f"2. Replacement detector, notes vs agent flag: n={len(y)}  notes also detect {y['replacement_in_notes'].mean():.1%}")
    gw = r[r["refund_reason_code"] == "GW-OTHER"]
    print(f"3. GW-OTHER refunds: n={len(gw)}  left UNCLASSIFIED={(gw['inferred_reason'] == 'UNCLASSIFIED').mean():.1%}")
    if os.path.exists("validation/labels.csv"):
        _, s = score(r)
        print(f"   labelled sample on file: n={s['n']} accuracy={s['accuracy']:.1%} (run --score for failures)")
    os.makedirs("validation", exist_ok=True)
    sample = gw.sample(min(100, len(gw)), random_state=7)[["ticket_id", "customer_message", "agent_notes"]]
    sample["true_reason"] = ""
    sample.to_csv("validation/label_sheet.csv", index=False)
    print("   wrote validation/label_sheet.csv (blind, git-ignored). Valid labels:", ", ".join(sorted(VALID)))


if __name__ == "__main__":
    main()
