"""Thin database layer. Uses psycopg2 when installed (Docker/Airflow image);
falls back to the `psql` CLI so the same SQL can be run on a machine that only
has PostgreSQL client tools."""
import io
import logging
import os
import subprocess

import pandas as pd

from . import config as C

log = logging.getLogger("nexusmart.db")

try:
    import psycopg2  # noqa
    HAVE_PG = True
except ImportError:  # pragma: no cover
    HAVE_PG = False


class Database:
    def __init__(self, cfg=None):
        self.cfg = cfg or C.DB

    # ------------------------------------------------------------------ psycopg2
    def _conn(self):
        return psycopg2.connect(**self.cfg)

    # ------------------------------------------------------------------ psql
    def _psql(self, args, stdin=None):
        env = dict(os.environ, PGPASSWORD=self.cfg["password"])
        cmd = ["psql", "-v", "ON_ERROR_STOP=1", "-X", "-q", "-h", self.cfg["host"], "-p", str(self.cfg["port"]),
               "-U", self.cfg["user"], "-d", self.cfg["dbname"]] + args
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env)
        if r.returncode != 0:
            raise RuntimeError(f"psql failed: {r.stderr.strip()}")
        return r.stdout

    # ------------------------------------------------------------------ API
    def execute(self, sql: str):
        """Run one or more statements in a single transaction."""
        if HAVE_PG:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(sql)
        else:
            self._psql(["-1"], stdin=sql)

    def execute_file(self, path):
        with open(path, encoding="utf-8") as f:
            sql = f.read()
        log.info("running %s", os.path.basename(str(path)))
        self.execute(sql)

    def copy_csv(self, table: str, csv_path, columns):
        cols = ", ".join(columns)
        if HAVE_PG:
            with self._conn() as conn, conn.cursor() as cur, open(csv_path, encoding="utf-8") as f:
                cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true)", f)
        else:
            self._psql(["-c", f"\\copy {table} ({cols}) FROM '{csv_path}' WITH (FORMAT csv, HEADER true)"])

    def query_df(self, sql: str) -> pd.DataFrame:
        sql = sql.strip().rstrip(";")
        if HAVE_PG:
            with self._conn() as conn:
                return pd.read_sql_query(sql, conn)
        out = self._psql(["-c", f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)"])
        return pd.read_csv(io.StringIO(out))

    def scalar(self, sql: str):
        df = self.query_df(sql)
        return df.iloc[0, 0] if len(df) else None
