-- =====================================================================
-- 07  Business questions (section 10 of the brief).
--     Each query starts with "-- name: <id>"; scripts/answer_questions.py
--     runs them and writes reports/answers/<id>.csv.
--     Revenue = Net Revenue (NMV - valid refunds) unless stated.
-- =====================================================================

-- name: kpi_overall
SELECT SUM(gross_amount) AS gross_sales, SUM(nmv) AS nmv, SUM(net_revenue) AS net_revenue,
       SUM(cogs_kept) AS cogs, SUM(net_revenue) - SUM(cogs_kept) AS margin,
       ROUND(100 * (SUM(net_revenue) - SUM(cogs_kept)) / SUM(net_revenue), 2) AS margin_pct,
       COUNT(DISTINCT order_id) AS orders_all,
       COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0) AS orders_non_cancelled,
       ROUND(SUM(nmv) / COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0), 2) AS aov,
       SUM(units) AS units,
       ROUND(100.0 * SUM(is_returned) FILTER (WHERE is_delivered_line = 1) / SUM(is_delivered_line), 2) AS return_rate_pct,
       ROUND(100.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 1) / COUNT(DISTINCT order_id), 2) AS cancellation_rate_pct,
       COUNT(DISTINCT customer_key) FILTER (WHERE is_cancelled = 0 AND customer_key <> -1) AS active_customers,
       SUM(discount_amount) FILTER (WHERE is_cancelled = 0) AS discounts_non_cancelled,
       SUM(returned_amount) AS refunds,
       SUM(shipping_fee) AS shipping_cost,
       SUM(net_revenue) - SUM(cogs_kept) - SUM(shipping_fee) AS margin_after_shipping
FROM mart.v_order_lines;

-- name: q01_category_revenue_margin
SELECT p.category,
       SUM(v.gross_amount) AS gross_sales, SUM(v.nmv) AS nmv, SUM(v.net_revenue) AS net_revenue,
       SUM(v.cogs_kept) AS cogs, SUM(v.net_revenue) - SUM(v.cogs_kept) AS margin,
       ROUND(100 * (SUM(v.net_revenue) - SUM(v.cogs_kept)) / NULLIF(SUM(v.net_revenue), 0), 2) AS margin_pct,
       ROUND(100 * SUM(v.net_revenue) / SUM(SUM(v.net_revenue)) OVER (), 2) AS revenue_share_pct
FROM mart.v_order_lines v JOIN dw.dim_product p ON p.product_key = v.product_key
GROUP BY p.category ORDER BY net_revenue DESC;

-- name: q02_province
SELECT l.province, SUM(v.nmv) AS nmv, SUM(v.net_revenue) AS net_revenue,
       ROUND(100 * SUM(v.net_revenue) / SUM(SUM(v.net_revenue)) OVER (), 2) AS share_pct,
       COUNT(DISTINCT v.order_id) FILTER (WHERE v.is_cancelled = 0) AS orders
FROM mart.v_order_lines v JOIN dw.dim_location l ON l.location_key = v.location_key
GROUP BY l.province ORDER BY net_revenue DESC;

-- name: q02_city_ranking
SELECT l.city, l.province, l.population_tier, SUM(v.nmv) AS nmv, SUM(v.net_revenue) AS net_revenue,
       ROUND(100 * SUM(v.net_revenue) / SUM(SUM(v.net_revenue)) OVER (), 3) AS share_pct,
       RANK() OVER (ORDER BY SUM(v.net_revenue) DESC) AS rank_desc
FROM mart.v_order_lines v JOIN dw.dim_location l ON l.location_key = v.location_key
WHERE l.location_key <> -1
GROUP BY l.city, l.province, l.population_tier ORDER BY net_revenue DESC;

-- name: q02_top5_city_share
WITH c AS (SELECT l.city, SUM(v.net_revenue) AS rev, SUM(v.nmv) AS nmv
           FROM mart.v_order_lines v JOIN dw.dim_location l ON l.location_key = v.location_key
           GROUP BY l.city)
SELECT ROUND(100 * SUM(rev) FILTER (WHERE rn <= 5) / SUM(rev), 2) AS top5_share_net_revenue_pct,
       ROUND(100 * SUM(nmv) FILTER (WHERE rn_n <= 5) / SUM(nmv), 2) AS top5_share_nmv_pct,
       string_agg(city, ', ' ORDER BY rn) FILTER (WHERE rn <= 5) AS top5_cities
FROM (SELECT *, ROW_NUMBER() OVER (ORDER BY rev DESC) rn, ROW_NUMBER() OVER (ORDER BY nmv DESC) rn_n FROM c) x;

-- name: q02_region_tier
SELECT l.region, l.population_tier, SUM(v.net_revenue) AS net_revenue,
       ROUND(100 * SUM(v.net_revenue) / (SELECT SUM(net_revenue) FROM mart.v_order_lines), 2) AS share_pct,
       COUNT(DISTINCT l.city) AS cities,
       ROUND(SUM(v.net_revenue) / COUNT(DISTINCT l.city)) AS revenue_per_city
FROM mart.v_order_lines v JOIN dw.dim_location l ON l.location_key = v.location_key
GROUP BY ROLLUP (l.region, l.population_tier) ORDER BY l.region NULLS LAST, l.population_tier NULLS LAST;

-- name: q03_monthly_trend
SELECT year_month, gross_sales, nmv, net_revenue, margin, orders, ROUND(aov, 2) AS aov, units,
       ROUND(100 * return_rate, 2) AS return_rate_pct, ROUND(100 * cancellation_rate, 2) AS cancellation_rate_pct,
       active_customers, shipping_cost,
       ROUND(100 * (net_revenue / LAG(net_revenue) OVER (ORDER BY year_month) - 1), 2) AS mom_growth_pct,
       ROUND(AVG(net_revenue) OVER (ORDER BY year_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)) AS net_revenue_3m_avg,
       ROUND(100 * margin / NULLIF(net_revenue, 0), 2) AS margin_pct
FROM mart.v_kpi_monthly ORDER BY year_month;

-- name: q04_rates_quarterly
SELECT d.year || '-' || d.quarter AS quarter,
       ROUND(100.0 * SUM(f.is_returned) FILTER (WHERE f.is_delivered_line = 1) / SUM(f.is_delivered_line), 2) AS return_rate_pct,
       ROUND(100.0 * COUNT(DISTINCT f.order_id) FILTER (WHERE f.is_cancelled = 1) / COUNT(DISTINCT f.order_id), 2) AS cancellation_rate_pct
FROM dw.fact_sales f JOIN dw.dim_date d ON d.date_key = f.date_key
GROUP BY 1 ORDER BY 1;

-- name: q05_profitability_waterfall_by_category
SELECT p.category,
       SUM(v.gross_amount) AS gross_sales,
       SUM(v.gross_amount) FILTER (WHERE v.is_cancelled = 1) AS lost_to_cancellation,
       SUM(v.discount_amount) FILTER (WHERE v.is_cancelled = 0) AS discounts,
       SUM(v.returned_amount) AS refunds,
       SUM(v.net_revenue) AS net_revenue,
       ROUND(100 * SUM(v.net_revenue) / SUM(v.gross_amount), 2) AS net_to_gross_pct,
       SUM(v.cogs_kept) AS cogs,
       SUM(v.net_revenue) - SUM(v.cogs_kept) AS margin,
       SUM(v.shipping_fee) AS shipping_cost,
       SUM(v.net_revenue) - SUM(v.cogs_kept) - SUM(v.shipping_fee) AS margin_after_shipping
FROM mart.v_order_lines v JOIN dw.dim_product p ON p.product_key = v.product_key
GROUP BY p.category ORDER BY net_to_gross_pct;

-- name: q06_clv_overall
WITH c AS (
    SELECT customer_key, SUM(net_revenue) AS rev, SUM(net_revenue) - SUM(cogs_kept) AS margin,
           COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0) AS orders
    FROM mart.v_order_lines WHERE customer_key <> -1 GROUP BY customer_key HAVING COUNT(*) FILTER (WHERE is_cancelled = 0) > 0)
SELECT COUNT(*) AS customers, ROUND(AVG(rev), 2) AS clv_net_revenue, ROUND(AVG(margin), 2) AS clv_margin,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rev) AS median_clv,
       ROUND(AVG(orders), 2) AS avg_orders,
       ROUND(100.0 * AVG((orders >= 2)::int), 2) AS repeat_purchase_rate_pct
FROM c;

-- name: q06_repeat_by_region
WITH c AS (
    SELECT v.customer_key, COUNT(DISTINCT v.order_id) AS orders, SUM(v.net_revenue) AS rev
    FROM mart.v_order_lines v WHERE v.is_cancelled = 0 AND v.customer_key <> -1 GROUP BY v.customer_key)
SELECT dc.region, COUNT(*) AS customers, ROUND(100.0 * AVG((orders >= 2)::int), 2) AS repeat_rate_pct,
       ROUND(AVG(rev), 0) AS clv_net_revenue
FROM c JOIN dw.dim_customer dc ON dc.customer_key = c.customer_key
GROUP BY dc.region ORDER BY repeat_rate_pct DESC;

-- name: q06_repeat_by_category
WITH c AS (
    SELECT v.customer_key, p.category, COUNT(DISTINCT v.order_id) AS orders, SUM(v.net_revenue) AS rev
    FROM mart.v_order_lines v JOIN dw.dim_product p ON p.product_key = v.product_key
    WHERE v.is_cancelled = 0 AND v.customer_key <> -1 GROUP BY v.customer_key, p.category)
SELECT category, COUNT(*) AS buyers, ROUND(100.0 * AVG((orders >= 2)::int), 2) AS repeat_in_category_pct,
       ROUND(AVG(rev), 0) AS revenue_per_buyer
FROM c GROUP BY category ORDER BY repeat_in_category_pct DESC;

-- name: q07_rfm_segments
SELECT dc.rfm_segment, COUNT(DISTINCT dc.customer_key) AS customers,
       ROUND(100.0 * COUNT(DISTINCT dc.customer_key) / SUM(COUNT(DISTINCT dc.customer_key)) OVER (), 2) AS customer_share_pct,
       SUM(v.net_revenue) AS net_revenue,
       ROUND(100 * SUM(v.net_revenue) / SUM(SUM(v.net_revenue)) OVER (), 2) AS revenue_share_pct,
       ROUND(SUM(v.net_revenue) / COUNT(DISTINCT dc.customer_key)) AS revenue_per_customer
FROM dw.dim_customer dc JOIN mart.v_order_lines v ON v.customer_key = dc.customer_key
WHERE dc.customer_key <> -1
GROUP BY dc.rfm_segment ORDER BY net_revenue DESC;

-- name: q08_seller_quality
-- Score (0-100) = 35% revenue + 25% (1-return rate) + 25% on-time rate + 15% (1-cancellation rate),
-- each component as a percentile rank among sellers with >= 100 order lines (volume floor so rates are stable).
WITH s AS (
    SELECT seller_key,
           COUNT(*) AS lines,
           SUM(net_revenue) AS net_revenue,
           1.0 * SUM(is_returned) FILTER (WHERE is_delivered_line = 1) / NULLIF(SUM(is_delivered_line), 0) AS return_rate,
           AVG(is_on_time) AS on_time_rate,
           1.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 1) / COUNT(DISTINCT order_id) AS cancel_rate,
           AVG(delivery_days) AS avg_delivery_days
    FROM mart.v_order_lines WHERE seller_key <> -1 GROUP BY seller_key HAVING COUNT(*) >= 100
), r AS (
    SELECT s.*,
           PERCENT_RANK() OVER (ORDER BY net_revenue)::numeric AS p_rev,
           PERCENT_RANK() OVER (ORDER BY return_rate DESC)::numeric AS p_ret,
           PERCENT_RANK() OVER (ORDER BY on_time_rate)::numeric AS p_ot,
           PERCENT_RANK() OVER (ORDER BY cancel_rate DESC)::numeric AS p_can
    FROM s)
SELECT ds.seller_id, ds.seller_name, ds.seller_tier, ds.rating, r.lines, ROUND(r.net_revenue) AS net_revenue,
       ROUND(100 * r.return_rate, 2) AS return_rate_pct, ROUND(100 * r.on_time_rate, 2) AS on_time_pct,
       ROUND(100 * r.cancel_rate, 2) AS cancel_rate_pct, ROUND(r.avg_delivery_days, 2) AS avg_delivery_days,
       ROUND(100 * (0.35 * p_rev + 0.25 * p_ret + 0.25 * p_ot + 0.15 * p_can), 1) AS quality_score,
       RANK() OVER (ORDER BY (0.35 * p_rev + 0.25 * p_ret + 0.25 * p_ot + 0.15 * p_can) DESC) AS quality_rank
FROM r JOIN dw.dim_seller ds ON ds.seller_key = r.seller_key
ORDER BY quality_rank;

-- name: q08_seller_tier
SELECT ds.seller_tier, COUNT(DISTINCT ds.seller_key) AS sellers, SUM(v.net_revenue) AS net_revenue,
       ROUND(SUM(v.net_revenue) / COUNT(DISTINCT ds.seller_key)) AS revenue_per_seller,
       ROUND(100.0 * SUM(v.is_returned) FILTER (WHERE v.is_delivered_line = 1) / SUM(v.is_delivered_line), 2) AS return_rate_pct,
       ROUND(100.0 * AVG(v.is_on_time), 2) AS on_time_pct,
       ROUND(AVG(v.delivery_days), 2) AS avg_delivery_days,
       ROUND(100.0 * COUNT(DISTINCT v.order_id) FILTER (WHERE v.is_cancelled = 1) / COUNT(DISTINCT v.order_id), 2) AS cancel_rate_pct
FROM mart.v_order_lines v JOIN dw.dim_seller ds ON ds.seller_key = v.seller_key
GROUP BY ds.seller_tier ORDER BY revenue_per_seller DESC;

-- name: q09_ontime_vs_returns
SELECT CASE WHEN delivery_days IS NULL THEN 'Not delivered / unknown'
            WHEN delivery_days <= 3 THEN '0-3 days' WHEN delivery_days <= 5 THEN '4-5 days'
            WHEN delivery_days <= 7 THEN '6-7 days' WHEN delivery_days <= 10 THEN '8-10 days' ELSE '11+ days' END AS delivery_bucket,
       COUNT(*) AS lines,
       ROUND(100.0 * SUM(is_returned) FILTER (WHERE is_delivered_line = 1) / NULLIF(SUM(is_delivered_line), 0), 2) AS return_rate_pct,
       ROUND(100.0 * SUM(is_returned) FILTER (WHERE is_delivered_line = 1 AND return_reason LIKE '%Late delivery%')
             / NULLIF(SUM(is_delivered_line), 0), 3) AS late_reason_return_rate_pct
FROM mart.v_order_lines GROUP BY 1 ORDER BY MIN(COALESCE(delivery_days, 999));

-- name: q09_ontime_summary
SELECT ROUND(100.0 * AVG(is_on_time), 2) AS on_time_rate_pct,
       ROUND(100.0 * SUM(is_returned) FILTER (WHERE is_on_time = 1) / NULLIF(COUNT(*) FILTER (WHERE is_on_time = 1), 0), 2) AS return_rate_on_time_pct,
       ROUND(100.0 * SUM(is_returned) FILTER (WHERE is_on_time = 0) / NULLIF(COUNT(*) FILTER (WHERE is_on_time = 0), 0), 2) AS return_rate_late_pct
FROM mart.v_order_lines WHERE is_delivered_line = 1;

-- name: q09_courier
SELECT courier, COUNT(DISTINCT order_id) AS orders, ROUND(AVG(delivery_days), 2) AS avg_delivery_days,
       ROUND(100.0 * AVG(is_on_time), 2) AS on_time_pct,
       ROUND(100.0 * SUM(is_returned) FILTER (WHERE is_delivered_line = 1) / NULLIF(SUM(is_delivered_line), 0), 2) AS return_rate_pct,
       ROUND(100.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 1) / COUNT(DISTINCT order_id), 2) AS cancel_rate_pct,
       ROUND(SUM(shipping_fee) / COUNT(DISTINCT order_id)) AS fee_per_order
FROM mart.v_order_lines GROUP BY courier ORDER BY orders DESC;

-- name: q10_product_quality
-- high sales = top 20% of products by NMV; high returns = return rate >= 2x overall rate, >= 30 delivered lines
WITH p AS (
    SELECT product_key, seller_key, SUM(nmv) AS nmv, SUM(is_delivered_line) AS delivered,
           SUM(is_returned) FILTER (WHERE is_delivered_line = 1) AS returned
    FROM mart.v_order_lines WHERE product_key <> -1 GROUP BY product_key, seller_key
), prod AS (
    SELECT product_key, SUM(nmv) AS nmv, SUM(delivered) AS delivered, SUM(returned) AS returned,
           (array_agg(seller_key ORDER BY nmv DESC))[1] AS main_seller_key,
           MAX(nmv) / NULLIF(SUM(nmv), 0) AS main_seller_share
    FROM p GROUP BY product_key
), overall AS (SELECT 1.0 * SUM(returned) / SUM(delivered) AS rr FROM prod),
ranked AS (SELECT prod.*, 1.0 * returned / NULLIF(delivered, 0) AS rr, PERCENT_RANK() OVER (ORDER BY nmv) AS nmv_pct FROM prod)
SELECT dp.product_id, dp.product_name, dp.category, ROUND(r.nmv) AS nmv, r.delivered, r.returned,
       ROUND(100 * r.rr, 2) AS return_rate_pct, ds.seller_id, ds.seller_name, ds.seller_tier,
       ROUND(100 * r.main_seller_share, 1) AS main_seller_share_pct
FROM ranked r CROSS JOIN overall o
JOIN dw.dim_product dp ON dp.product_key = r.product_key
JOIN dw.dim_seller ds ON ds.seller_key = r.main_seller_key
WHERE r.nmv_pct >= 0.8 AND r.delivered >= 30 AND r.rr >= 2 * o.rr
ORDER BY r.rr DESC;

-- name: q10_seller_concentration
-- Are high-sales/high-return products concentrated in particular sellers? Compare share of products vs share of flagged products.
WITH p AS (
    SELECT product_key, MAX(seller_key) AS seller_key, SUM(nmv) AS nmv, SUM(is_delivered_line) AS delivered,
           SUM(is_returned) FILTER (WHERE is_delivered_line = 1) AS returned
    FROM mart.v_order_lines WHERE product_key <> -1 GROUP BY product_key
), o AS (SELECT 1.0 * SUM(returned) / SUM(delivered) AS rr FROM p),
f AS (SELECT p.*, (PERCENT_RANK() OVER (ORDER BY nmv) >= 0.8 AND delivered >= 30
                   AND 1.0 * returned / NULLIF(delivered, 0) >= 2 * (SELECT rr FROM o))::int AS flagged FROM p)
SELECT ds.seller_id, ds.seller_name, ds.seller_tier, COUNT(*) AS products, SUM(flagged) AS flagged_products,
       ROUND(100.0 * SUM(flagged) / COUNT(*), 1) AS flagged_pct,
       ROUND(100.0 * SUM(returned) / NULLIF(SUM(delivered), 0), 2) AS seller_return_rate_pct
FROM f JOIN dw.dim_seller ds ON ds.seller_key = f.seller_key
GROUP BY ds.seller_id, ds.seller_name, ds.seller_tier HAVING SUM(flagged) > 0
ORDER BY flagged_products DESC, seller_return_rate_pct DESC;

-- name: q11_seasonality
WITH daily AS (
    SELECT d.full_date, d.event_name, SUM(v.nmv) AS nmv, SUM(v.net_revenue) AS net_revenue,
           COUNT(DISTINCT v.order_id) AS orders_all,
           COUNT(DISTINCT v.order_id) FILTER (WHERE v.is_cancelled = 1) AS orders_cancelled,
           SUM(v.is_delivered_line) AS delivered, SUM(v.is_returned) FILTER (WHERE v.is_delivered_line = 1) AS returned
    FROM dw.dim_date d JOIN mart.v_order_lines v ON v.date_key = d.date_key
    GROUP BY d.full_date, d.event_name)
SELECT event_name, COUNT(*) AS days, ROUND(AVG(nmv)) AS avg_daily_nmv, ROUND(AVG(net_revenue)) AS avg_daily_net_revenue,
       ROUND(100 * (AVG(net_revenue) / (SELECT AVG(net_revenue) FROM daily WHERE event_name = 'Regular day') - 1), 1) AS uplift_vs_regular_pct,
       ROUND(100.0 * SUM(orders_cancelled) / SUM(orders_all), 2) AS cancellation_rate_pct,
       ROUND(100.0 * SUM(returned) / NULLIF(SUM(delivered), 0), 2) AS return_rate_pct
FROM daily GROUP BY event_name ORDER BY avg_daily_net_revenue DESC;

-- name: q12_discounts
SELECT CASE WHEN discount_pct = 0 THEN '0%' WHEN discount_pct <= 10 THEN '5-10%' WHEN discount_pct <= 20 THEN '15-20%'
            WHEN discount_pct <= 30 THEN '25-30%' ELSE '40-50%' END AS discount_band,
       COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0) AS orders,
       ROUND(100.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0)
             / SUM(COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0)) OVER (), 2) AS order_share_pct,
       ROUND(SUM(gross_amount) FILTER (WHERE is_cancelled = 0) / COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0)) AS gross_basket,
       ROUND(SUM(nmv) / COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0)) AS aov,
       SUM(net_revenue) AS net_revenue,
       ROUND(100 * (SUM(net_revenue) - SUM(cogs_kept)) / NULLIF(SUM(net_revenue), 0), 2) AS margin_pct,
       ROUND(100.0 * SUM(is_returned) FILTER (WHERE is_delivered_line = 1) / NULLIF(SUM(is_delivered_line), 0), 2) AS return_rate_pct,
       ROUND(100.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 1) / COUNT(DISTINCT order_id), 2) AS cancel_rate_pct
FROM mart.v_order_lines GROUP BY 1 ORDER BY MIN(discount_pct);

-- name: q12_discount_share_trend
SELECT year_month, ROUND(100.0 * SUM(discount_amount) FILTER (WHERE is_cancelled = 0)
                          / SUM(gross_amount) FILTER (WHERE is_cancelled = 0), 2) AS discount_pct_of_gross,
       ROUND(100.0 * COUNT(DISTINCT order_id) FILTER (WHERE discount_pct > 0) / COUNT(DISTINCT order_id), 2) AS discounted_order_share_pct
FROM mart.v_order_lines GROUP BY year_month ORDER BY year_month;

-- name: q13_region_delivery
SELECT l.region, l.province, COUNT(DISTINCT v.order_id) AS orders, ROUND(AVG(v.delivery_days), 2) AS avg_delivery_days,
       ROUND(100.0 * AVG(v.is_on_time), 2) AS on_time_pct,
       ROUND(100.0 * COUNT(DISTINCT v.order_id) FILTER (WHERE v.is_cancelled = 1) / COUNT(DISTINCT v.order_id), 2) AS cancel_rate_pct,
       ROUND(100.0 * SUM(v.is_returned) FILTER (WHERE v.is_delivered_line = 1) / NULLIF(SUM(v.is_delivered_line), 0), 2) AS return_rate_pct
FROM mart.v_order_lines v JOIN dw.dim_location l ON l.location_key = v.location_key
WHERE l.location_key <> -1
GROUP BY ROLLUP (l.region, l.province) ORDER BY l.region NULLS LAST, avg_delivery_days DESC;

-- name: q14_payment_methods
SELECT payment_method, COUNT(DISTINCT order_id) AS orders,
       ROUND(100.0 * COUNT(DISTINCT order_id) / SUM(COUNT(DISTINCT order_id)) OVER (), 2) AS order_share_pct,
       ROUND(100.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 1) / COUNT(DISTINCT order_id), 2) AS cancel_rate_pct,
       ROUND(100.0 * SUM(is_returned) FILTER (WHERE is_delivered_line = 1) / NULLIF(SUM(is_delivered_line), 0), 2) AS return_rate_pct,
       ROUND(SUM(nmv) / NULLIF(COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled = 0), 0)) AS aov
FROM mart.v_order_lines GROUP BY payment_method ORDER BY orders DESC;

-- name: q14_payment_data_quality
SELECT p.payment_method, p.payment_status, COUNT(*) AS payments, COUNT(*) FILTER (WHERE p.payment_date IS NULL) AS missing_date,
       COUNT(*) FILTER (WHERE p.amount IS NULL) AS missing_amount
FROM stg.payments p GROUP BY 1, 2 ORDER BY 1, 3 DESC;

-- name: q14_status_consistency
-- Does the payment status agree with the order status? (data-quality explanation for payment/cancel links)
SELECT o.payment_method, o.order_status,
       COUNT(*) AS orders,
       COUNT(*) FILTER (WHERE ps.statuses LIKE '%Cancelled%') AS payment_says_cancelled,
       COUNT(*) FILTER (WHERE ps.statuses LIKE '%Paid%') AS payment_says_paid
FROM stg.orders o
LEFT JOIN (SELECT order_id, string_agg(payment_status, ',') AS statuses FROM stg.payments GROUP BY order_id) ps
       ON ps.order_id = o.order_id
GROUP BY 1, 2 ORDER BY 1, 2;

-- name: q15_profitability_trend
SELECT year_month, gross_sales, net_revenue, margin, shipping_cost,
       ROUND(100 * margin / net_revenue, 2) AS margin_pct,
       ROUND(100 * (margin - shipping_cost) / net_revenue, 2) AS margin_after_shipping_pct,
       ROUND(100 * shipping_cost / net_revenue, 2) AS shipping_pct_of_revenue,
       ROUND(100 * (gross_sales - net_revenue) / gross_sales, 2) AS leakage_pct_of_gross
FROM mart.v_kpi_monthly ORDER BY year_month;

-- name: q15_cancelled_shipping_cost
SELECT COUNT(DISTINCT order_id) AS cancelled_orders_with_shipment, ROUND(SUM(shipping_fee)) AS shipping_spent_on_cancelled
FROM mart.v_order_lines WHERE is_cancelled = 1 AND courier <> 'None';

-- name: q15_category_mix_trend
SELECT v.year_month, p.category, SUM(v.net_revenue) AS net_revenue,
       ROUND(100 * SUM(v.net_revenue) / SUM(SUM(v.net_revenue)) OVER (PARTITION BY v.year_month), 2) AS share_pct,
       ROUND(100 * (SUM(v.net_revenue) - SUM(v.cogs_kept)) / NULLIF(SUM(v.net_revenue), 0), 2) AS margin_pct,
       ROUND(100.0 * SUM(v.discount_amount) FILTER (WHERE v.is_cancelled = 0) / NULLIF(SUM(v.gross_amount) FILTER (WHERE v.is_cancelled = 0), 0), 2) AS discount_pct_of_gross
FROM mart.v_order_lines v JOIN dw.dim_product p ON p.product_key = v.product_key
GROUP BY v.year_month, p.category ORDER BY v.year_month, net_revenue DESC;

-- name: q15_margin_bridge
-- Margin % in first vs last 6 months, holding each driver at its H1-2024 level
WITH h AS (
    SELECT CASE WHEN year_month <= '2024-06' THEN 'H1-2024' WHEN year_month >= '2025-01' THEN 'H1-2025' END AS period,
           SUM(gross_amount) FILTER (WHERE is_cancelled = 0) AS gross_kept,
           SUM(discount_amount) FILTER (WHERE is_cancelled = 0) AS discounts,
           SUM(returned_amount) AS refunds, SUM(net_revenue) AS net_revenue, SUM(cogs_kept) AS cogs,
           SUM(shipping_fee) AS shipping
    FROM mart.v_order_lines GROUP BY 1)
SELECT period, ROUND(net_revenue) AS net_revenue,
       ROUND(100 * discounts / gross_kept, 2) AS discount_pct_of_gross,
       ROUND(100 * refunds / gross_kept, 2) AS refund_pct_of_gross,
       ROUND(100 * cogs / gross_kept, 2) AS cogs_pct_of_gross,
       ROUND(100 * (net_revenue - cogs) / net_revenue, 2) AS margin_pct,
       ROUND(100 * shipping / net_revenue, 2) AS shipping_pct_of_revenue,
       ROUND(100 * (net_revenue - cogs - shipping) / net_revenue, 2) AS margin_after_shipping_pct
FROM h WHERE period IS NOT NULL ORDER BY period;
