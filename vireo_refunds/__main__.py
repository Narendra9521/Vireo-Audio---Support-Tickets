import argparse, os, sys
from .clean import load, clean_tickets, enrich
from .report import add_inference, build


def main(argv=None):
    ap = argparse.ArgumentParser(description="Vireo refund summary: clean, classify, report.")
    ap.add_argument("--data", default="data", help="folder with tickets/agents/orders/products CSVs")
    ap.add_argument("--out", default="outputs")
    a = ap.parse_args(argv)
    for f in ("tickets.csv", "agents.csv", "orders.csv", "products.csv"):
        if not os.path.exists(os.path.join(a.data, f)):
            sys.exit(f"Missing {a.data}/{f}. Put the four CSVs from the pack in {a.data}/ (see README).")
    os.makedirs(a.out, exist_ok=True)
    tickets, agents, orders, products = load(a.data)
    clean, bridge = clean_tickets(tickets)
    df = add_inference(enrich(clean, agents, orders, products))
    build(df, bridge, a.out)
    print("Reconciliation:")
    for step, rs, n in bridge:
        print(f"  {step:<62}{rs:>16,.0f}")
    print(f"Wrote {a.out}/refund_summary.xlsx, tickets_clean.csv, refund_reasons.csv")


if __name__ == "__main__":
    main()
