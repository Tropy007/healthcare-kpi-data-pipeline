"""Extract, clean, validate, and load clinic data into SQLite.

Usage:  python src/etl.py
Creates clinic_kpis.db with clean tables, KPI views, and a validation log,
then writes outputs/weekly_kpis.csv.
"""
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VALID_STATUS = {"Completed", "No-show", "Cancelled"}


# ---------- Transform ----------
def parse_mixed_dates(s: pd.Series) -> pd.Series:
    """Parse ISO (2026-01-05), US (01/05/2026), and 05-Jan-2026 formats."""
    out = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    for fmt in ["%m/%d/%Y", "%d-%b-%Y"]:
        out = out.fillna(pd.to_datetime(s, format=fmt, errors="coerce"))
    return out


def standardize_clinic(s: pd.Series) -> pd.Series:
    """Map spelling and case variants to one canonical clinic name."""
    key = s.str.strip().str.lower()
    mapping = {"north clinic": "North Clinic", "riverside clinic": "Riverside Clinic",
               "riverside": "Riverside Clinic", "downtown clinic": "Downtown Clinic"}
    return key.map(mapping)


def parse_amount(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(r"[$,]", "", regex=True), errors="coerce")


def clean_appointments(raw: pd.DataFrame):
    df = raw.drop_duplicates()
    log = {"appointments_raw_rows": len(raw), "appointments_duplicates_removed": len(raw) - len(df)}
    df = df.assign(clinic=standardize_clinic(df["clinic"]),
                   booked_date=parse_mixed_dates(df["booked_date"]),
                   appointment_date=parse_mixed_dates(df["appointment_date"]))
    bad_order = df["booked_date"] > df["appointment_date"]
    missing_status = ~df["status"].isin(VALID_STATUS)
    log["appointments_booked_after_visit"] = int(bad_order.sum())
    log["appointments_missing_status"] = int(missing_status.sum())
    log["appointments_unmapped_clinic"] = int(df["clinic"].isna().sum())
    df = df[~bad_order & ~missing_status & df["clinic"].notna()].copy()
    df["lead_days"] = (df["appointment_date"] - df["booked_date"]).dt.days
    df["week_start"] = (df["appointment_date"] - pd.to_timedelta(df["appointment_date"].dt.weekday, unit="D")).dt.date
    log["appointments_clean_rows"] = len(df)
    return df, log


def clean_claims(raw: pd.DataFrame, valid_appointment_ids):
    df = raw.drop_duplicates("claim_id").assign(billed_amount=parse_amount(raw["billed_amount"]))
    negative = df["billed_amount"] <= 0
    orphan = ~df["appointment_id"].isin(valid_appointment_ids)
    log = {"claims_raw_rows": len(raw), "claims_nonpositive_amount": int(negative.sum()),
           "claims_orphaned": int(orphan.sum())}
    df = df[~negative & ~orphan].copy()
    log["claims_clean_rows"] = len(df)
    return df, log


# ---------- Validate ----------
def validate(appts: pd.DataFrame, claims: pd.DataFrame) -> pd.DataFrame:
    """Checks that must pass before data is loaded. Returns one row per check."""
    checks = [
        ("appointment_id is unique", appts["appointment_id"].is_unique),
        ("claim_id is unique", claims["claim_id"].is_unique),
        ("no missing appointment dates", appts["appointment_date"].notna().all()),
        ("lead_days is never negative", (appts["lead_days"] >= 0).all()),
        ("status uses allowed values", appts["status"].isin(VALID_STATUS).all()),
        ("billed amounts are positive", (claims["billed_amount"] > 0).all()),
        ("every claim links to an appointment", claims["appointment_id"].isin(appts["appointment_id"]).all()),
        ("paid claims have days_to_payment", claims.loc[claims["claim_status"] == "Paid", "days_to_payment"].notna().all()),
    ]
    return pd.DataFrame(checks, columns=["check", "passed"])


# ---------- Load ----------
def load(appts, claims, checks, log, con):
    appts.assign(booked_date=appts["booked_date"].dt.date.astype(str),
                 appointment_date=appts["appointment_date"].dt.date.astype(str),
                 week_start=appts["week_start"].astype(str)
                 ).to_sql("appointments", con, index=False, if_exists="replace")
    claims.to_sql("claims", con, index=False, if_exists="replace")
    checks.assign(passed=checks["passed"].astype(int)).to_sql("validation_checks", con, index=False, if_exists="replace")
    pd.DataFrame(list(log.items()), columns=["metric", "value"]).to_sql("etl_log", con, index=False, if_exists="replace")
    con.executescript((ROOT / "sql" / "kpi_views.sql").read_text())


def run(raw_dir=ROOT / "data" / "raw", con=None):
    raw_dir = Path(raw_dir)
    con = con or sqlite3.connect(":memory:")
    appts, log_a = clean_appointments(pd.read_csv(raw_dir / "appointments_raw.csv"))
    claims, log_c = clean_claims(pd.read_csv(raw_dir / "claims_raw.csv"), set(appts["appointment_id"]))
    checks = validate(appts, claims)
    if not checks["passed"].all():
        raise ValueError("Validation failed:\n" + checks[~checks["passed"]].to_string(index=False))
    load(appts, claims, checks, {**log_a, **log_c}, con)
    return con


if __name__ == "__main__":
    db = ROOT / "clinic_kpis.db"
    db.unlink(missing_ok=True)
    con = run(con=sqlite3.connect(db))
    print(pd.read_sql("SELECT * FROM etl_log", con).to_string(index=False))
    print(pd.read_sql("SELECT * FROM validation_checks", con).to_string(index=False))
    out = ROOT / "outputs"; out.mkdir(exist_ok=True)
    pd.read_sql("SELECT * FROM weekly_kpis", con).to_csv(out / "weekly_kpis.csv", index=False)
    print("\nWrote outputs/weekly_kpis.csv")
