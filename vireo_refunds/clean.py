"""Load and clean the Vireo helpdesk export. Every decision here is deliberate; see README."""
import numpy as np
import pandas as pd

LEGACY_DIVISOR = 100          # Freshdesk stored money in paise (verified: all 638 dup pairs differ by exactly x100)
REPLACEMENT_SHIPPING = 340    # policy s5: reverse pickup + forward shipping, on top of unit cost


def load(data_dir):
    p = lambda f: f"{data_dir}/{f}"
    tickets = pd.read_csv(p("tickets.csv"), parse_dates=["created_at", "first_response_at", "resolved_at"])
    agents = pd.read_csv(p("agents.csv"), parse_dates=["from_date", "to_date"])
    orders = pd.read_csv(p("orders.csv"), parse_dates=["order_date"])
    products = pd.read_csv(p("products.csv"))
    return tickets, agents, orders, products


def clean_tickets(tickets):
    """Return (clean_df, bridge) where bridge is the raw -> clean reconciliation."""
    t = tickets.copy()
    raw = t["refund_amount_inr"].sum()
    raw_rows = t["refund_amount_inr"].notna().sum()

    legacy = t["source_system"].eq("legacy_fd")
    t["refund_inr"] = np.where(legacy, t["refund_amount_inr"] / LEGACY_DIVISOR, t["refund_amount_inr"])
    after_units = t["refund_inr"].sum()

    # Duplicates: same ticket_id under both source systems. Keep the helpdesk copy (rupees, same text).
    t["_pref"] = t["source_system"].map({"helpdesk": 0, "legacy_fd": 1}).fillna(2)
    t = t.sort_values(["ticket_id", "_pref"])
    n_dupe_ids = t["ticket_id"].duplicated().sum()
    t = t.drop_duplicates("ticket_id", keep="first").drop(columns="_pref")
    clean_total = t["refund_inr"].sum()

    t["month"] = t["created_at"].dt.to_period("M").astype(str)   # decision: month = ticket created_at, IST as exported
    t["quarter"] = t["created_at"].dt.to_period("Q").astype(str)
    bridge = [
        ("Raw export total (as Finance read it)", raw, int(raw_rows)),
        ("Less: Freshdesk rows stored in paise (divide by 100)", after_units - raw, None),
        ("Subtotal: after unit fix, before de-duplication", after_units, None),
        (f"Less: {n_dupe_ids} tickets imported twice (kept helpdesk copy)", clean_total - after_units, None),
        ("Clean refund total", clean_total, int(t["refund_inr"].notna().sum())),
    ]
    return t, bridge


def enrich(t, agents, orders, products):
    # Agent: roster has one row per assignment -> pick the row valid on the ticket's date.
    a = agents.rename(columns={"team": "agent_team"})
    m = t.merge(a, on="agent_id", how="left")
    ok = (m["created_at"] >= m["from_date"]) & (m["to_date"].isna() | (m["created_at"] <= m["to_date"]))
    # tickets created before the agent's from_date still get the earliest row rather than being dropped
    m["_ok"] = ok
    m = m.sort_values(["ticket_id", "_ok", "from_date"], ascending=[True, False, False]).drop_duplicates("ticket_id")
    m = m.drop(columns="_ok")

    m = m.merge(products[["sku", "product_name", "unit_cost_inr"]], left_on="product_sku", right_on="sku", how="left").drop(columns="sku")

    # Order: direct join on order_id; fallback customer_id + sku, latest order on or before ticket date.
    o = orders.rename(columns={"sku": "product_sku"})
    direct = m.merge(o[["order_id", "order_value_inr", "lot_code"]], on="order_id", how="left")
    miss = direct["order_value_inr"].isna() & direct["refund_inr"].notna()
    if miss.any():
        fb = direct.loc[miss, ["ticket_id", "customer_id", "product_sku", "created_at"]].sort_values("created_at")
        o2 = o.sort_values("order_date")[["customer_id", "product_sku", "order_date", "order_value_inr", "lot_code"]]
        got = pd.merge_asof(fb, o2, left_on="created_at", right_on="order_date", by=["customer_id", "product_sku"])
        got = got.set_index("ticket_id")
        for c in ("order_value_inr", "lot_code"):
            direct.loc[miss, c] = direct.loc[miss, "ticket_id"].map(got[c])
        direct["order_matched_via"] = np.where(direct["order_id"].notna() & ~miss, "order_id",
                                       np.where(direct["order_value_inr"].notna(), "customer+sku", "none"))
    return direct
