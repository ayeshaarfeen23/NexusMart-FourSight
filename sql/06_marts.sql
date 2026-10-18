-- =====================================================================
-- 06  Reporting views on top of the star schema (Power BI may use the
--     star schema directly; these views document the metric definitions
--     and are used to produce the executive-summary figures).
-- =====================================================================
CREATE OR REPLACE VIEW mart.v_order_lines AS
SELECT f.*,
       d.full_date AS order_date, d.year_month, d.month_start, d.event_name, d.is_ramadan, d.is_eid_ul_fitr,
       d.is_eid_ul_adha, d.is_11_11, d.is_black_friday, d.is_independence_day,
       (1 - f.is_cancelled) AS is_kept_order,
       CASE WHEN f.is_cancelled = 0 THEN f.net_amount ELSE 0 END                         AS nmv,
       CASE WHEN f.is_cancelled = 0 THEN f.net_amount - f.returned_amount ELSE 0 END     AS net_revenue,
       CASE WHEN f.is_cancelled = 0 AND f.is_returned = 0 THEN f.cost_amount ELSE 0 END  AS cogs_kept,
       CASE WHEN f.is_cancelled = 0 THEN f.quantity ELSE 0 END                           AS units
FROM dw.fact_sales f JOIN dw.dim_date d ON d.date_key = f.date_key;

-- Standard business metrics per month (definitions exactly as in the brief)
CREATE OR REPLACE VIEW mart.v_kpi_monthly AS
SELECT year_month,
       SUM(gross_amount)                                              AS gross_sales,
       SUM(nmv)                                                       AS nmv,
       SUM(net_revenue)                                               AS net_revenue,
       SUM(cogs_kept)                                                 AS cogs,
       SUM(net_revenue) - SUM(cogs_kept)                              AS margin,
       COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0)       AS orders,
       SUM(nmv) / NULLIF(COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0), 0) AS aov,
       SUM(units)                                                     AS units,
       1.0 * SUM(is_returned) FILTER (WHERE is_delivered_line = 1)
           / NULLIF(SUM(is_delivered_line), 0)                        AS return_rate,
       1.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 1)
           / NULLIF(COUNT(DISTINCT order_id), 0)                      AS cancellation_rate,
       COUNT(DISTINCT customer_key) FILTER (WHERE is_cancelled = 0)   AS active_customers,
       SUM(shipping_fee)                                              AS shipping_cost
FROM mart.v_order_lines
GROUP BY year_month;

-- Seller scorecard (imported into Power BI as a reporting table, 1:1 with dim_seller on seller_key).
-- Score (0-100) = 35% revenue + 25% (1-return rate) + 25% on-time rate + 15% (1-cancellation rate),
-- each component a percentile rank among sellers with >= 100 order lines (volume floor for stable rates).
CREATE OR REPLACE VIEW mart.v_seller_scorecard AS
WITH s AS (
    SELECT seller_key, COUNT(*) AS lines, SUM(net_revenue) AS net_revenue,
           1.0 * SUM(is_returned) FILTER (WHERE is_delivered_line = 1) / NULLIF(SUM(is_delivered_line), 0) AS return_rate,
           AVG(is_on_time) AS on_time_rate,
           1.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 1) / COUNT(DISTINCT order_id) AS cancel_rate,
           AVG(delivery_days) AS avg_delivery_days
    FROM mart.v_order_lines WHERE seller_key <> -1 GROUP BY seller_key HAVING COUNT(*) >= 100
), r AS (
    SELECT s.*,
           PERCENT_RANK() OVER (ORDER BY net_revenue)::numeric       AS p_rev,
           PERCENT_RANK() OVER (ORDER BY return_rate DESC)::numeric  AS p_ret,
           PERCENT_RANK() OVER (ORDER BY on_time_rate)::numeric      AS p_ot,
           PERCENT_RANK() OVER (ORDER BY cancel_rate DESC)::numeric  AS p_can
    FROM s)
SELECT seller_key, lines, ROUND(net_revenue, 2) AS net_revenue, ROUND(return_rate, 4) AS return_rate,
       ROUND(on_time_rate, 4) AS on_time_rate, ROUND(cancel_rate, 4) AS cancel_rate,
       ROUND(avg_delivery_days, 2) AS avg_delivery_days,
       ROUND(100 * (0.35 * p_rev + 0.25 * p_ret + 0.25 * p_ot + 0.15 * p_can), 1) AS quality_score,
       RANK() OVER (ORDER BY (0.35 * p_rev + 0.25 * p_ret + 0.25 * p_ot + 0.15 * p_can) DESC) AS quality_rank
FROM r;
