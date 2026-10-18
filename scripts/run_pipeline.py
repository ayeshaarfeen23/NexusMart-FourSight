"""Run the full pipeline without Airflow (same task functions, same order).
Usage:  python scripts/run_pipeline.py [--from TASK]"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import tasks  # noqa: E402

ORDER = ["extract", "validate_raw", "clean", "load_staging", "build_dimensions", "build_fact", "quality_checks"]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="extract", choices=ORDER)
    ap.add_argument("--run-id", default=datetime.now().strftime("manual__%Y%m%dT%H%M%S"))
    a = ap.parse_args()
    for name in ORDER[ORDER.index(a.start):]:
        logging.info("==== %s ====", name)
        getattr(tasks, name)(run_id=a.run_id)
    logging.info("pipeline finished, run_id=%s", a.run_id)
