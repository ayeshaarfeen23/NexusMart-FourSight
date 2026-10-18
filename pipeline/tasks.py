"""The seven pipeline tasks. Airflow (dags/nexusmart_pipeline.py) calls these
functions; scripts/run_pipeline.py calls the same functions without Airflow."""
import hashlib
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import clean as cleaning
from . import config as C
from .db import Database

log = logging.getLogger("nexusmart.tasks")

STG_TABLES = ["locations", "sellers", "products", "product_id_map", "customers", "customer_id_map", "orders",
              "order_items", "payments", "shipping", "returns"]


def _run_id(run_id=None):
    return run_id or datetime.now().strftime("manual__%Y%m%dT%H%M%S")


def _task_log(db, run_id, task, read=None, rejected=None, loaded=None, note=""):
    def v(x):
        return "NULL" if x is None else str(int(x))
    note = note.replace("'", "''")
    db.execute(f"INSERT INTO dq.task_log(run_id, task, rows_read, rows_rejected, rows_loaded, note) "
               f"VALUES ('{run_id}', '{task}', {v(read)}, {v(rejected)}, {v(loaded)}, '{note}')")
    log.info("%s: read=%s rejected=%s loaded=%s %s", task, read, rejected, loaded, note)


def _ensure_ddl(db):
    db.execute_file(C.SQL_DIR / "01_staging_ddl.sql")
    db.execute_file(C.SQL_DIR / "02_dw_ddl.sql")


# ------------------------------------------------------------------ 1. extract
def extract(run_id=None):
    """Snapshot the raw CSVs into the run's work area with a manifest (rows, md5)."""
    run_id = _run_id(run_id)
    snap = C.WORK_DIR / "raw_snapshot"
    snap.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name in C.REQUIRED_COLUMNS:
        src = C.RAW_DIR / f"{name}.csv"
        if not src.exists():
            raise FileNotFoundError(f"Missing raw file: {src}")
        shutil.copy2(src, snap / src.name)
        md5 = hashlib.md5(src.read_bytes()).hexdigest()
        rows = sum(1 for _ in open(src, encoding="utf-8")) - 1
        manifest.append(dict(file=src.name, rows=rows, bytes=src.stat().st_size, md5=md5))
    (C.WORK_DIR / "manifest.json").write_text(json.dumps(dict(run_id=run_id, files=manifest), indent=2))
    db = Database()
    _ensure_ddl(db)
    _task_log(db, run_id, "extract", read=sum(m["rows"] for m in manifest), note=f"{len(manifest)} files")
    return manifest


# ------------------------------------------------------------------ 2. validate_raw
def validate_raw(run_id=None):
    """Structure + first-pass quality checks on raw files. Fails on missing files,
    missing required columns, empty files or non-unique primary keys beyond exact duplicates."""
    run_id = _run_id(run_id)
    problems, report = [], []
    for name, cols in C.REQUIRED_COLUMNS.items():
        p = C.RAW_DIR / f"{name}.csv"
        if not p.exists():
            problems.append(f"{name}: file missing")
            continue
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        missing = [c for c in cols if c not in df.columns]
        if missing:
            problems.append(f"{name}: missing columns {missing}")
        if len(df) == 0:
            problems.append(f"{name}: no rows")
        pk = cols[0]
        exact = int(df.duplicated().sum())
        pk_dup = int(df.drop_duplicates()[pk].duplicated().sum()) if pk in df else 0
        blanks = {c: int((df[c].str.strip() == "").sum()) for c in cols if c in df}
        report.append(dict(file=name, rows=len(df), exact_duplicates=exact, pk_conflicts=pk_dup,
                           extra_columns=[c for c in df.columns if c not in cols], blanks=blanks))
        if pk_dup > 0.01 * len(df):
            problems.append(f"{name}: {pk_dup} conflicting duplicate keys (>1%)")
    out = C.WORK_DIR / "dq"
    out.mkdir(parents=True, exist_ok=True)
    (out / "raw_validation.json").write_text(json.dumps(report, indent=2))
    db = Database()
    _task_log(db, run_id, "validate_raw", read=sum(r["rows"] for r in report),
              note="OK" if not problems else "; ".join(problems))
    if problems:
        raise ValueError("Raw validation failed: " + "; ".join(problems))
    return report


# ------------------------------------------------------------------ 3. clean
def clean(run_id=None):
    run_id = _run_id(run_id)
    counts = cleaning.run(C.WORK_DIR / "raw_snapshot" if (C.WORK_DIR / "raw_snapshot").exists() else C.RAW_DIR,
                          C.WORK_DIR)
    db = Database()
    _task_log(db, run_id, "clean", read=counts["raw"].sum(), rejected=counts["rejected"].fillna(0).sum(),
              loaded=counts["clean"].sum())
    return counts.to_dict(orient="records")


# ------------------------------------------------------------------ 4. load_staging
def load_staging(run_id=None):
    run_id = _run_id(run_id)
    db = Database()
    _ensure_ddl(db)
    clean_dir = C.WORK_DIR / "clean"
    db.execute("TRUNCATE " + ", ".join(f"stg.{t}" for t in STG_TABLES))
    total = 0
    for t in STG_TABLES:
        path = clean_dir / f"{t}.csv"
        cols = pd.read_csv(path, nrows=0).columns.tolist()
        db.copy_csv(f"stg.{t}", str(path), cols)
        n = int(db.scalar(f"SELECT COUNT(*) FROM stg.{t}"))
        total += n
        log.info("stg.%s loaded %d rows", t, n)

    # DQ artefacts for this run (delete-then-insert by run_id => idempotent)
    dq_dir = C.WORK_DIR / "dq"
    db.execute(f"DELETE FROM dq.dq_log WHERE run_id='{run_id}'; DELETE FROM dq.rejects WHERE run_id='{run_id}';"
               f"DELETE FROM dq.row_counts WHERE run_id='{run_id}';")
    tmp = C.WORK_DIR / "tmp"
    tmp.mkdir(exist_ok=True)
    lg = pd.read_csv(dq_dir / "dq_log.csv")
    lg.insert(0, "run_id", run_id)
    lg.to_csv(tmp / "dq_log.csv", index=False)
    db.copy_csv("dq.dq_log", str(tmp / "dq_log.csv"),
                ["run_id", "table_name", "column_name", "issue", "action", "rows_affected", "note"])
    rj = pd.read_csv(C.WORK_DIR / "rejects" / "all_rejects.csv", dtype=str)
    rj.insert(0, "run_id", run_id)
    rj.to_csv(tmp / "rejects.csv", index=False)
    db.copy_csv("dq.rejects", str(tmp / "rejects.csv"), ["run_id", "source_table", "source_key", "reject_reason", "record_json"])
    rc = pd.read_csv(dq_dir / "row_counts.csv")
    rc.insert(0, "run_id", run_id)
    rc = rc.rename(columns={"table": "table_name", "raw": "raw_rows", "clean": "clean_rows", "rejected": "rejected_rows"})
    rc["rejected_rows"] = rc["rejected_rows"].fillna(0).astype(int)
    rc[["run_id", "table_name", "raw_rows", "clean_rows", "rejected_rows"]].to_csv(tmp / "row_counts.csv", index=False)
    db.copy_csv("dq.row_counts", str(tmp / "row_counts.csv"), ["run_id", "table_name", "raw_rows", "clean_rows", "rejected_rows"])
    _task_log(db, run_id, "load_staging", read=total, rejected=len(rj), loaded=total)
    return total


# ------------------------------------------------------------------ 5. build_dimensions
def build_dimensions(run_id=None):
    run_id = _run_id(run_id)
    db = Database()
    db.execute_file(C.SQL_DIR / "03_build_dimensions.sql")
    counts = {t: int(db.scalar(f"SELECT COUNT(*) FROM dw.{t}"))
              for t in ["dim_date", "dim_customer", "dim_product", "dim_seller", "dim_location"]}
    _task_log(db, run_id, "build_dimensions", loaded=sum(counts.values()), note=json.dumps(counts))
    return counts


# ------------------------------------------------------------------ 6. build_fact
def build_fact(run_id=None):
    run_id = _run_id(run_id)
    db = Database()
    db.execute_file(C.SQL_DIR / "04_build_fact.sql")
    n_src = int(db.scalar("SELECT COUNT(*) FROM stg.order_items"))
    n = int(db.scalar("SELECT COUNT(*) FROM dw.fact_sales"))
    db.execute_file(C.SQL_DIR / "06_marts.sql")
    _task_log(db, run_id, "build_fact", read=n_src, rejected=n_src - n, loaded=n)
    return n


# ------------------------------------------------------------------ 7. quality_checks
CHECKS = [
    # name, severity, sql returning one number, python predicate, expected text
    ("fact rows = staged order lines", "critical",
     "SELECT (SELECT COUNT(*) FROM dw.fact_sales) - (SELECT COUNT(*) FROM stg.order_items)", lambda v: v == 0, "0"),
    ("fact grain unique (order_item_id)", "critical",
     "SELECT COUNT(*) - COUNT(DISTINCT order_item_id) FROM dw.fact_sales", lambda v: v == 0, "0"),
    ("no NULL foreign keys in fact", "critical",
     "SELECT COUNT(*) FROM dw.fact_sales WHERE date_key IS NULL OR customer_key IS NULL OR product_key IS NULL "
     "OR seller_key IS NULL OR location_key IS NULL", lambda v: v == 0, "0"),
    ("net amount reconciles with staging", "critical",
     "SELECT ABS((SELECT SUM(net_amount) FROM dw.fact_sales) - "
     "(SELECT SUM(quantity*unit_price - discount_amount) FROM stg.order_items))", lambda v: v < 1, "< 1 PKR"),
    ("valid refunds reconcile with staging", "critical",
     "SELECT ABS((SELECT SUM(returned_amount) FROM dw.fact_sales) - "
     "(SELECT COALESCE(SUM(refund_amount),0) FROM stg.returns WHERE is_valid_return=1))", lambda v: v < 1, "< 1 PKR"),
    ("allocated shipping fees reconcile with shipments", "critical",
     "SELECT ABS((SELECT SUM(shipping_fee) FROM dw.fact_sales) - (SELECT SUM(shipping_fee) FROM stg.shipping))",
     lambda v: v < 1, "< 1 PKR"),
    ("negative amounts in fact", "critical",
     "SELECT COUNT(*) FROM dw.fact_sales WHERE gross_amount < 0 OR net_amount < 0 OR cost_amount < 0 "
     "OR returned_amount < 0 OR quantity <= 0", lambda v: v == 0, "0"),
    ("refund never exceeds line net", "critical",
     "SELECT COUNT(*) FROM dw.fact_sales WHERE returned_amount > net_amount + 1", lambda v: v == 0, "0"),
    ("order dates inside business window", "critical",
     "SELECT COUNT(*) FROM dw.fact_sales f JOIN dw.dim_date d ON d.date_key=f.date_key "
     "WHERE d.full_date NOT BETWEEN '2024-01-01' AND '2025-06-30'", lambda v: v == 0, "0"),
    ("unknown customer share", "warning",
     "SELECT AVG((customer_key=-1)::int)::float FROM dw.fact_sales", lambda v: v <= C.QC_MAX_UNKNOWN_SHARE,
     f"<= {C.QC_MAX_UNKNOWN_SHARE}"),
    ("unknown product share", "critical",
     "SELECT AVG((product_key=-1)::int)::float FROM dw.fact_sales", lambda v: v <= C.QC_MAX_UNKNOWN_SHARE,
     f"<= {C.QC_MAX_UNKNOWN_SHARE}"),
    ("unknown location share", "critical",
     "SELECT AVG((location_key=-1)::int)::float FROM dw.fact_sales", lambda v: v <= C.QC_MAX_UNKNOWN_SHARE,
     f"<= {C.QC_MAX_UNKNOWN_SHARE}"),
    ("distinct canonical categories", "critical",
     "SELECT COUNT(DISTINCT category) FROM dw.dim_product WHERE product_key <> -1", lambda v: v == 12, "12"),
    ("dimension unknown members present", "critical",
     "SELECT (SELECT COUNT(*) FROM dw.dim_customer WHERE customer_key=-1)+(SELECT COUNT(*) FROM dw.dim_product WHERE product_key=-1)"
     "+(SELECT COUNT(*) FROM dw.dim_seller WHERE seller_key=-1)+(SELECT COUNT(*) FROM dw.dim_location WHERE location_key=-1)"
     "+(SELECT COUNT(*) FROM dw.dim_date WHERE date_key=0)", lambda v: v == 5, "5"),
    ("duplicate customer master ids", "critical",
     "SELECT COUNT(*) - COUNT(DISTINCT customer_id) FROM dw.dim_customer", lambda v: v == 0, "0"),
    ("order-line reject rate", "critical",
     "WITH lr AS (SELECT run_id FROM dq.task_log WHERE task='load_staging' ORDER BY logged_at DESC LIMIT 1) "
     "SELECT 1.0*(SELECT COUNT(*) FROM dq.rejects r, lr WHERE r.source_table='order_items' AND r.run_id=lr.run_id)"
     "/ NULLIF((SELECT raw_rows FROM dq.row_counts c, lr WHERE c.table_name='order_items' AND c.run_id=lr.run_id),0)",
     lambda v: v <= C.REJECT_RATE_FAIL, f"<= {C.REJECT_RATE_FAIL}"),
]


def quality_checks(run_id=None):
    run_id = _run_id(run_id)
    db = Database()
    db.execute(f"DELETE FROM dq.quality_results WHERE run_id='{run_id}'")
    failed = []
    rows = []
    for name, sev, sql, pred, expected in CHECKS:
        v = db.scalar(sql.format(run_id=run_id))
        v = 0 if pd.isna(v) else float(v)
        ok = bool(pred(v))
        rows.append((name, sev, ok, v, expected))
        db.execute("INSERT INTO dq.quality_results(run_id, check_name, severity, passed, observed, expected) VALUES "
                   f"('{run_id}', '{name}', '{sev}', {ok}, '{v:g}', '{expected}')")
        log.info("[%s] %-45s observed=%g expected %s", "PASS" if ok else "FAIL", name, v, expected)
        if not ok and sev == "critical":
            failed.append(name)
    n = int(db.scalar("SELECT COUNT(*) FROM dw.fact_sales"))
    _task_log(db, run_id, "quality_checks", read=n, note=f"{len(rows) - len(failed)}/{len(rows)} passed")
    if failed:
        raise ValueError(f"Critical quality checks failed: {failed}")
    return rows
