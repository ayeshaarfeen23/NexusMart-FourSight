-- =====================================================================
-- 04  Build FactSales (grain = one row per order line).
--     Full rebuild inside one transaction -> idempotent, no duplicates.
--     Returns are aggregated per order line BEFORE joining, using valid
--     (non-Rejected) returns only, so the grain is never violated.
--     Shipping fee is per order; it is allocated to lines by gross share
--     so the line fees sum back exactly to the order fee.
--     Delivery durations outside 0..30 days (date errors) are left NULL.
--     On-time = delivered within 5 days of the order date (~70th percentile).
-- =====================================================================
TRUNCATE dw.fact_sales RESTART IDENTITY;

WITH ret AS (
    SELECT order_item_id,
           1                                   AS is_returned,
           SUM(refund_amount)                  AS returned_amount,
           MIN(return_date)                    AS return_date,
           string_agg(DISTINCT return_reason, ', ' ORDER BY return_reason) AS return_reason,
           CASE WHEN bool_or(return_status = 'Refunded') THEN 'Refunded' ELSE 'Approved' END AS return_status
    FROM stg.returns
    WHERE is_valid_return = 1
    GROUP BY order_item_id
), line AS (
    SELECT i.*,
           i.quantity * i.unit_price AS gross,
           SUM(i.quantity * i.unit_price) OVER (PARTITION BY i.order_id) AS order_gross,
           COUNT(*) OVER (PARTITION BY i.order_id) AS order_lines
    FROM stg.order_items i
), first_order AS (
    SELECT DISTINCT ON (customer_id) customer_id, order_id
    FROM stg.orders WHERE order_status <> 'Cancelled'
    ORDER BY customer_id, order_date, order_id
)
INSERT INTO dw.fact_sales (
    date_key, customer_key, product_key, seller_key, location_key, return_date_key,
    order_id, order_item_id, quantity, unit_price, gross_amount, discount_pct, discount_amount, net_amount,
    unit_cost, cost_amount, shipping_fee, shipping_days, delivery_days, is_on_time, courier,
    is_cancelled, is_in_transit, is_delivered_line, is_returned, returned_amount, return_reason, return_status,
    order_status, payment_method, channel, discount_code, is_first_order, is_repaired)
SELECT
    to_char(o.order_date, 'YYYYMMDD')::int,
    COALESCE(dc.customer_key, -1),
    COALESCE(dp.product_key, -1),
    COALESCE(ds.seller_key, -1),
    COALESCE(dl.location_key, -1),
    COALESCE(to_char(r.return_date, 'YYYYMMDD')::int, 0),
    l.order_id, l.order_item_id, l.quantity, l.unit_price,
    ROUND(l.gross, 2),
    o.discount_pct,
    l.discount_amount,
    ROUND(l.gross - l.discount_amount, 2),
    l.unit_cost,
    ROUND(l.unit_cost * l.quantity, 2),
    ROUND(COALESCE(sh.shipping_fee, 0) *
          CASE WHEN l.order_gross > 0 THEN l.gross / l.order_gross ELSE 1.0 / l.order_lines END, 6),
    CASE WHEN (sh.delivered_date - sh.shipped_date) BETWEEN 0 AND 30 THEN sh.delivered_date - sh.shipped_date END,
    CASE WHEN (sh.delivered_date - o.order_date) BETWEEN 0 AND 30 THEN sh.delivered_date - o.order_date END,
    CASE WHEN (sh.delivered_date - o.order_date) NOT BETWEEN 0 AND 30 OR sh.delivered_date IS NULL THEN NULL
         WHEN (sh.delivered_date - o.order_date) <= 5 THEN 1 ELSE 0 END,
    COALESCE(sh.courier, 'None'),
    (o.order_status = 'Cancelled')::int,
    (o.order_status = 'In Transit')::int,
    (o.order_status NOT IN ('Cancelled', 'In Transit'))::int,
    COALESCE(r.is_returned, 0),
    COALESCE(r.returned_amount, 0),
    r.return_reason,
    r.return_status,
    o.order_status, o.payment_method, o.channel, COALESCE(o.discount_code, 'None'),
    (fo.order_id IS NOT NULL)::int,
    GREATEST(l.price_repaired, l.qty_repaired, l.discount_repaired, o.order_date_repaired)
FROM line l
JOIN stg.orders o              ON o.order_id = l.order_id
LEFT JOIN stg.shipping sh      ON sh.order_id = l.order_id
LEFT JOIN ret r                ON r.order_item_id = l.order_item_id
LEFT JOIN first_order fo       ON fo.order_id = l.order_id
LEFT JOIN dw.dim_customer dc   ON dc.customer_id = o.customer_id
LEFT JOIN dw.dim_product dp    ON dp.product_id = l.product_id
LEFT JOIN dw.dim_seller ds     ON ds.seller_id = l.seller_id
LEFT JOIN dw.dim_location dl   ON dl.city_id = o.ship_city_id;

ANALYZE dw.fact_sales;
