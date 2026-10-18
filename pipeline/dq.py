"""Data-quality bookkeeping: every rule logs what it did, and every record that
cannot be repaired is written to a reject file with a reason code."""
import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger("nexusmart.dq")


class DQ:
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.events = []        # rule-level log (data quality report)
        self.rejects = {}       # table -> list[DataFrame]
        self.counts = {}        # table -> {"raw": n, "clean": n, "rejected": n}

    def event(self, table, column, issue, action, rows, note=""):
        rows = int(rows)
        self.events.append(dict(table=table, column=column, issue=issue,
                                action=action, rows_affected=rows, note=note))
        if rows:
            log.info("[%s.%s] %s -> %s : %d rows %s", table, column, issue, action, rows, note)

    def reject(self, table, df, reason):
        if df is None or len(df) == 0:
            return
        out = df.copy()
        out.insert(0, "reject_reason", reason)
        # keep source values as text so nothing is lost
        out = out.astype(str)
        self.rejects.setdefault(table, []).append(out)
        self.event(table, "*", "unrepairable record", f"rejected ({reason})", len(df))

    def set_count(self, table, stage, n):
        self.counts.setdefault(table, {})[stage] = int(n)

    def write(self):
        dq_dir = self.work_dir / "dq"
        rej_dir = self.work_dir / "rejects"
        dq_dir.mkdir(parents=True, exist_ok=True)
        rej_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(self.events).to_csv(dq_dir / "dq_log.csv", index=False)
        all_rej = []
        for table, frames in self.rejects.items():
            df = pd.concat(frames, ignore_index=True)
            df.to_csv(rej_dir / f"{table}_rejects.csv", index=False)
            self.counts.setdefault(table, {})["rejected"] = len(df)
            key = df.columns[1]
            all_rej.append(pd.DataFrame({
                "source_table": table,
                "source_key": df[key],
                "reject_reason": df["reject_reason"],
                "record_json": df.drop(columns=["reject_reason"]).to_dict(orient="records"),
            }))
        if all_rej:
            r = pd.concat(all_rej, ignore_index=True)
            r["record_json"] = r["record_json"].map(json.dumps)
        else:
            r = pd.DataFrame(columns=["source_table", "source_key", "reject_reason", "record_json"])
        r.to_csv(rej_dir / "all_rejects.csv", index=False)
        cnt = pd.DataFrame([dict(table=t, **v) for t, v in self.counts.items()])
        cnt.to_csv(dq_dir / "row_counts.csv", index=False)
        return cnt
