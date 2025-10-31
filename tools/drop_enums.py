import os
from sqlalchemy import create_engine

URL = os.getenv("DATABASE_URL") or "postgresql+psycopg://antifraud:PASS@127.0.0.1:5433/antifraud"
engine = create_engine(URL, future=True)

stmts = [
    "DROP TYPE IF EXISTS payment_status_enum",
    "DROP TYPE IF EXISTS report_enum",
    "DROP TYPE IF EXISTS risk_enum",
    "DROP TYPE IF EXISTS plan_enum",
    "DROP TABLE IF EXISTS alembic_version"
]

with engine.begin() as conn:
    for s in stmts:
        conn.exec_driver_sql(s)
print("Enums (и alembic_version) очищены.")
