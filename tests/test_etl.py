import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
import pytest
from etl import parse_mixed_dates, standardize_clinic, parse_amount, validate, run, clean_appointments
from generate_synthetic_data import generate


def test_parse_mixed_dates():
    s = pd.Series(["2026-01-05", "01/05/2026", "05-Jan-2026"])
    assert parse_mixed_dates(s).nunique() == 1


def test_standardize_clinic_variants():
    s = pd.Series(["NORTH CLINIC ", "north clinic", "Riverside", "Riverside clinic"])
    assert list(standardize_clinic(s)) == ["North Clinic", "North Clinic", "Riverside Clinic", "Riverside Clinic"]


def test_parse_amount_strips_symbols():
    assert list(parse_amount(pd.Series(["$1,234.50", "99.9"]))) == [1234.5, 99.9]


def test_cleaning_removes_bad_rows():
    appts, _ = generate(n_appointments=800, seed=3)
    clean, log = clean_appointments(appts)
    assert clean["appointment_id"].is_unique
    assert (clean["lead_days"] >= 0).all()
    assert log["appointments_duplicates_removed"] > 0


def test_validation_flags_bad_data():
    appts = pd.DataFrame({"appointment_id": ["A1", "A1"], "appointment_date": [pd.NaT, pd.NaT],
                          "lead_days": [-1, 2], "status": ["Completed", "Unknown"]})
    claims = pd.DataFrame({"claim_id": ["C1", "C1"], "appointment_id": ["A9", "A9"], "billed_amount": [-5.0, 10.0],
                           "claim_status": ["Paid", "Paid"], "days_to_payment": [None, 3]})
    assert not validate(appts, claims)["passed"].any()


def test_end_to_end_pipeline(tmp_path):
    appts, claims = generate(n_appointments=800, seed=4, weeks=6)
    appts.to_csv(tmp_path / "appointments_raw.csv", index=False)
    claims.to_csv(tmp_path / "claims_raw.csv", index=False)
    con = run(raw_dir=tmp_path)
    weekly = pd.read_sql("SELECT * FROM weekly_kpis", con)
    assert len(weekly) == 6
    assert weekly["no_show_rate_pct"].between(0, 100).all()
    assert pd.read_sql("SELECT MIN(passed) AS ok FROM validation_checks", con)["ok"][0] == 1
