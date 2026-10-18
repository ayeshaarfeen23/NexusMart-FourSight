"""NexusMart end-to-end ELT pipeline.

extract >> validate_raw >> clean >> load_staging >> build_dimensions >> build_fact >> quality_checks

* Paths and DB credentials come from environment variables (docker-compose .env)
  and may be overridden with Airflow Variables of the same name (e.g. NEXUS_RAW_DIR).
* Idempotent: staging is truncated and reloaded, dimensions are upserted on
  natural keys (stable surrogate keys), the fact is rebuilt in one transaction,
  DQ tables are written per run_id with delete-then-insert.
* Each task logs rows read / rejected / loaded to dq.task_log.
* quality_checks raises (fails the DAG run) when a critical check fails;
  clean raises when the order-line reject rate exceeds the threshold.
"""
import os
import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator

PROJECT_DIR = os.getenv("NEXUS_PROJECT_DIR", "/opt/nexusmart")
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# Optional overrides from Airflow Variables (fall back to env / defaults)
for var in ("NEXUS_RAW_DIR", "NEXUS_WORK_DIR", "NEXUS_DB_HOST", "NEXUS_DB_PORT", "NEXUS_DB_NAME"):
    try:
        val = Variable.get(var, default_var=None)
    except Exception:  # metadata DB not reachable at parse time
        val = None
    if val:
        os.environ[var] = val

from pipeline import tasks  # noqa: E402  (import after env is set)

DEFAULT_ARGS = {
    "owner": "nexusmart-data",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(minutes=30),
}


def _call(fn_name):
    def _run(**context):
        return getattr(tasks, fn_name)(run_id=context["run_id"])
    _run.__name__ = fn_name
    return _run


with DAG(
    dag_id="nexusmart_pipeline",
    description="Raw CSV -> clean -> PostgreSQL star schema -> quality gates",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2025, 7, 1),
    schedule="@daily",
    catchup=False,
    max_active_runs=1,
    tags=["nexusmart", "datathon"],
    doc_md=__doc__,
) as dag:
    steps = ["extract", "validate_raw", "clean", "load_staging", "build_dimensions", "build_fact", "quality_checks"]
    ops = []
    for s in steps:
        op = PythonOperator(task_id=s, python_callable=_call(s))
        if s in ("validate_raw", "quality_checks"):
            op.retries = 0          # a data-quality failure will not fix itself on retry
        ops.append(op)
    for upstream, downstream in zip(ops, ops[1:]):
        upstream >> downstream
