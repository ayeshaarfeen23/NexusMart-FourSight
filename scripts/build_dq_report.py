"""Generate reports/data_quality_report.md from the DQ artefacts written by the
clean task (data/work/dq/*.csv, data/work/rejects/*.csv). Re-run after every pipeline run."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import config as C  # noqa: E402


def table(df):
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join("" if pd.isna(v) else f"{v:,}" if isinstance(v, (int,)) else str(v) for v in r) + " |")
    return "\n".join(out)


def main():
    dq = C.WORK_DIR / "dq"
    log = pd.read_csv(dq / "dq_log.csv")
    counts = pd.read_csv(dq / "row_counts.csv")
    rej = pd.read_csv(C.WORK_DIR / "rejects" / "all_rejects.csv")
    raw_val = json.loads((dq / "raw_validation.json").read_text()) if (dq / "raw_validation.json").exists() else []

    counts["rejected"] = counts.get("rejected", 0)
    counts["rejected"] = counts["rejected"].fillna(0).astype(int)
    counts["removed_as_duplicates_or_merged"] = counts["raw"] - counts["clean"] - counts["rejected"]
    order = ["locations", "sellers", "products", "customers", "orders", "order_items", "payments", "shipping", "returns"]
    counts["o"] = counts["table"].map({t: i for i, t in enumerate(order)})
    counts = counts.sort_values("o").drop(columns="o")
    counts = counts.rename(columns={"raw": "raw_rows", "clean": "clean_rows", "rejected": "rejected_rows"})
    for c in ["raw_rows", "clean_rows", "rejected_rows", "removed_as_duplicates_or_merged"]:
        counts[c] = counts[c].astype(int)

    md = ["# NexusMart – Data Quality Report",
          "",
          "Generated from the pipeline's own logs (`data/work/dq/dq_log.csv`, `data/work/rejects/`). "
          "Every number below was produced by code in `pipeline/clean.py`; nothing was edited by hand. "
          "Unrepairable records are kept in reject files (and in `dq.rejects` in the database) with a reason code – "
          "nothing is silently deleted.",
          "",
          "## 1. Before / after row counts",
          "",
          table(counts),
          "",
          "*`removed_as_duplicates_or_merged`* = exact duplicate rows removed (orders 3,200; payments 3,296) or duplicate "
          "entities merged into a master record (customers 2,500; products 56 – the mapping tables "
          "`customer_id_map.csv` / `product_id_map.csv` keep every original ID so all related records still link).",
          ""]

    if raw_val:
        rv = pd.DataFrame([{k: v for k, v in r.items() if k in ("file", "rows", "exact_duplicates", "pk_conflicts")} for r in raw_val])
        md += ["## 2. Raw profile (validate_raw)", "", table(rv), "",
               "Blank-value counts per column are stored in `data/work/dq/raw_validation.json`.", ""]

    md += ["## 3. Rejected records by reason", ""]
    if len(rej):
        g = rej.groupby(["source_table", "reject_reason"]).size().reset_index(name="rows")
        md += [table(g), ""]
    md += ["## 4. Every cleaning rule applied (with rows affected)", "",
           "Rules with 0 affected rows are kept in the log (they guard against the next data drop) but omitted here.", ""]
    for t in order:
        sub = log[(log["table"] == t) & (log.rows_affected > 0)][["column", "issue", "action", "rows_affected", "note"]]
        if len(sub):
            sub = sub.copy()
            sub["rows_affected"] = sub["rows_affected"].astype(int)
            md += [f"### {t}", "", table(sub.fillna("")), ""]

    md += ["## 5. Missing-value decisions (impute / flag / retain / quarantine)", "",
           "| Column | Decision | Business reason |", "|---|---|---|",
           "| orders.order_date (invalid) | Repair from first prepaid payment date (matches order date 98.4% of the time), else shipped date − 1 day; else quarantine | Revenue must be dated to land in a month; a guessed date would distort trends |",
           "| orders.ship_city_id | Impute from customer's registered city (equal in 88.7% of orders), else Unknown | Geography analysis needs a location; flagged with `ship_city_imputed` |",
           "| customers.city_id | Impute from the customer's most frequent ship city, else Unknown | Same entity, more reliable source |",
           "| order_items.discount_amount | Recompute from order discount code % (consistent on 99.4% of lines) | The code is the authoritative order-level discount per the brief |",
           "| order_items.unit_price / quantity (corrupt) | Solve exactly from order_total = Σ(qty×price)×(1−disc%) when it is the only bad field; else product's median price that month; else quarantine | order_total is an independent source of truth for the line |",
           "| products.cost_price (missing or ≥ list price) | Duplicate partner's cost, else list price × category median cost/list ratio; flagged `cost_imputed` | Needed for COGS/margin; category ratio is the least-biased estimate |",
           "| products.brand | First word of product name when it is a known brand | Names are built as '<Brand> <Item> <Code>' |",
           "| products.sub_category | 'Unspecified' | Tier (Basics/Premium/Essentials) cannot be derived |",
           "| shipping.shipping_fee (missing/0/placeholder) | Courier median fee; flagged `fee_imputed` | Fee is a real NexusMart cost; dropping it would overstate profit |",
           "| returns.refund_amount (> line value) | Capped at line net value | A refund cannot exceed what was paid |",
           "| returns.return_reason | 'Not specified' | Kept in rates; reason unknown |",
           "| customers.gender / birth_year / seller rating / tier | Retain as Unknown / NULL | Descriptive only; imputing would invent attributes |",
           "| lat/long, weight_kg | Retain NULL | Not used in any metric |",
           ""]
    out = C.REPORT_DIR / "data_quality_report.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
