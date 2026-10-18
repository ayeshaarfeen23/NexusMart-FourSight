"""Run sql/07_business_questions.sql against the warehouse and write one CSV per
question to reports/answers/, plus an all-in-one markdown dump."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import config as C  # noqa: E402
from pipeline.db import Database  # noqa: E402


def queries(path):
    text = Path(path).read_text(encoding="utf-8")
    parts = re.split(r"^-- name:\s*(\S+)\s*$", text, flags=re.M)
    for i in range(1, len(parts), 2):
        body = "\n".join(l for l in parts[i + 1].splitlines() if not l.strip().startswith("--")).strip()
        yield parts[i], body


if __name__ == "__main__":
    db = Database()
    out = C.REPORT_DIR / "answers"
    out.mkdir(parents=True, exist_ok=True)
    md = ["# Business question outputs (generated)\n"]
    for name, sql in queries(C.SQL_DIR / "07_business_questions.sql"):
        df = db.query_df(sql)
        df.to_csv(out / f"{name}.csv", index=False)
        try:
            body = df.head(40).to_markdown(index=False)
        except ImportError:
            body = "```\n" + df.head(40).to_string(index=False) + "\n```"
        md.append(f"\n## {name}\n\n{body}")
        print(f"{name}: {len(df)} rows")
    (out / "ALL_ANSWERS.md").write_text("\n".join(md), encoding="utf-8")
