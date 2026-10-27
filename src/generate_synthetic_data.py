"""Generate messy synthetic clinic data for the KPI pipeline.

All records are randomly generated. No real patients, clinics, or
payers are represented. The files deliberately contain the problems
real exports have: mixed date formats, inconsistent clinic names,
currency symbols, duplicates, missing values, and impossible values.
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 11
CLINICS = {"North Clinic": ["North Clinic", "north clinic", "NORTH CLINIC ", "North Clinic"],
           "Riverside Clinic": ["Riverside Clinic", "Riverside clinic", "Riverside"],
           "Downtown Clinic": ["Downtown Clinic", "downtown clinic", "Downtown Clinic"]}
PAYERS = ["Payer A", "Payer B", "Payer C", "Self-pay"]


def _fmt_dates(dates, rng):
    """Write dates in three different formats, as mixed exports often do."""
    style = rng.integers(0, 3, len(dates))
    return np.where(style == 0, dates.dt.strftime("%Y-%m-%d"),
           np.where(style == 1, dates.dt.strftime("%m/%d/%Y"), dates.dt.strftime("%d-%b-%Y")))


def generate(n_appointments=6000, seed=SEED, start="2026-01-05", weeks=26):
    rng = np.random.default_rng(seed)
    clinic = rng.choice(list(CLINICS), n_appointments, p=[0.4, 0.35, 0.25])
    appt_date = pd.to_datetime(start) + pd.to_timedelta(rng.integers(0, weeks * 7, n_appointments), unit="D")
    lead_days = rng.exponential(12, n_appointments).round().astype(int)
    booked = appt_date - pd.to_timedelta(lead_days, unit="D")
    p_noshow = np.clip(0.08 + 0.006 * lead_days + np.where(clinic == "Downtown Clinic", 0.05, 0), 0, 0.6)
    status = np.where(rng.random(n_appointments) < p_noshow, "No-show",
             np.where(rng.random(n_appointments) < 0.05, "Cancelled", "Completed"))

    appts = pd.DataFrame({
        "appointment_id": [f"A{200000 + i}" for i in range(n_appointments)],
        "patient_id": [f"P{v}" for v in rng.integers(10000, 14000, n_appointments)],
        "clinic": [rng.choice(CLINICS[c]) for c in clinic],
        "booked_date": _fmt_dates(pd.Series(booked), rng),
        "appointment_date": _fmt_dates(pd.Series(appt_date), rng),
        "status": status,
    })
    appts.loc[rng.random(n_appointments) < 0.02, "status"] = np.nan          # missing status
    bad = rng.choice(n_appointments, 15, replace=False)                      # booked after visit
    appts.loc[bad, "booked_date"] = (pd.Series(appt_date[bad]) + pd.Timedelta(days=5)).dt.strftime("%Y-%m-%d").values
    appts = pd.concat([appts, appts.sample(60, random_state=seed)], ignore_index=True)

    done = appts.drop_duplicates("appointment_id")
    done = done[done["status"] == "Completed"]
    n = len(done)
    payer = rng.choice(PAYERS, n, p=[0.35, 0.3, 0.2, 0.15])
    amount = rng.gamma(4, 45, n).round(2)
    denied = rng.random(n) < np.select([payer == "Payer C", payer == "Self-pay"], [0.16, 0.03], 0.08)
    days_to_pay = np.where(denied, np.nan, rng.gamma(3, np.where(payer == "Payer B", 12, 8), n).round())
    claims = pd.DataFrame({
        "claim_id": [f"C{500000 + i}" for i in range(n)],
        "appointment_id": done["appointment_id"].values,
        "payer": payer,
        "billed_amount": [f"${a:,.2f}" if rng.random() < 0.5 else f"{a}" for a in amount],
        "claim_status": np.where(denied, "Denied", "Paid"),
        "days_to_payment": days_to_pay,
    })
    claims.loc[rng.choice(n, 10, replace=False), "billed_amount"] = "-25.00"   # impossible negatives
    return appts, claims


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "data" / "raw"
    appts, claims = generate()
    appts.to_csv(out / "appointments_raw.csv", index=False)
    claims.to_csv(out / "claims_raw.csv", index=False)
    print(f"Wrote {len(appts)} appointment rows and {len(claims)} claim rows")
