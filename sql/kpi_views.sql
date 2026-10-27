-- KPI views built on the clean, validated tables

-- Weekly operational and revenue-cycle KPIs
DROP VIEW IF EXISTS weekly_kpis;
CREATE VIEW weekly_kpis AS
WITH appt AS (
    SELECT week_start,
           COUNT(*)                                                    AS scheduled,
           SUM(status = 'Completed')                                   AS completed,
           SUM(status = 'No-show')                                     AS no_shows,
           AVG(lead_days)                                              AS avg_lead_days
    FROM appointments
    GROUP BY week_start
),
clm AS (
    SELECT a.week_start,
           COUNT(*)                                                    AS claims,
           SUM(c.claim_status = 'Denied')                              AS denied,
           SUM(CASE WHEN c.claim_status = 'Paid' THEN c.billed_amount ELSE 0 END) AS collected,
           AVG(c.days_to_payment)                                      AS avg_days_to_payment
    FROM claims c
    JOIN appointments a USING (appointment_id)
    GROUP BY a.week_start
)
SELECT appt.week_start,
       appt.scheduled,
       appt.completed,
       ROUND(100.0 * appt.no_shows / appt.scheduled, 1)                AS no_show_rate_pct,
       ROUND(appt.avg_lead_days, 1)                                    AS avg_lead_days,
       clm.claims,
       ROUND(100.0 * clm.denied / clm.claims, 1)                       AS denial_rate_pct,
       ROUND(clm.collected, 2)                                         AS collected_usd,
       ROUND(clm.avg_days_to_payment, 1)                               AS avg_days_to_payment
FROM appt
LEFT JOIN clm USING (week_start)
ORDER BY appt.week_start;

-- KPIs by clinic
DROP VIEW IF EXISTS clinic_kpis;
CREATE VIEW clinic_kpis AS
SELECT a.clinic,
       COUNT(*)                                                         AS scheduled,
       ROUND(100.0 * SUM(a.status = 'No-show') / COUNT(*), 1)           AS no_show_rate_pct,
       ROUND(AVG(a.lead_days), 1)                                       AS avg_lead_days,
       ROUND(100.0 * SUM(c.claim_status = 'Denied') / COUNT(c.claim_id), 1) AS denial_rate_pct
FROM appointments a
LEFT JOIN claims c USING (appointment_id)
GROUP BY a.clinic
ORDER BY no_show_rate_pct DESC;

-- Revenue-cycle KPIs by payer
DROP VIEW IF EXISTS payer_kpis;
CREATE VIEW payer_kpis AS
SELECT payer,
       COUNT(*)                                                         AS claims,
       ROUND(100.0 * SUM(claim_status = 'Denied') / COUNT(*), 1)        AS denial_rate_pct,
       ROUND(AVG(days_to_payment), 1)                                   AS avg_days_to_payment,
       ROUND(SUM(CASE WHEN claim_status = 'Paid' THEN billed_amount ELSE 0 END), 2) AS collected_usd
FROM claims
GROUP BY payer
ORDER BY denial_rate_pct DESC;
