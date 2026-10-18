-- =====================================================================
-- 03  Build / update dimensions (idempotent upserts on natural keys;
--     surrogate keys stay stable across reruns). Unknown members = -1.
-- =====================================================================

-- ---------------------------------------------------------------- DimDate
INSERT INTO dw.dim_date (date_key, full_date, day_of_month, day_name, day_of_week, week_of_year, week_start,
                         month_num, month_name, month_start, year_month, quarter, year, is_weekend,
                         is_ramadan, is_eid_ul_fitr, is_eid_ul_adha, is_independence_day, is_11_11, is_black_friday,
                         is_event_day, event_name)
SELECT to_char(d, 'YYYYMMDD')::int, d::date, extract(day FROM d), to_char(d, 'FMDay'), extract(isodow FROM d),
       extract(week FROM d), date_trunc('week', d)::date, extract(month FROM d), to_char(d, 'FMMonth'),
       date_trunc('month', d)::date, to_char(d, 'YYYY-MM'), 'Q' || extract(quarter FROM d), extract(year FROM d),
       extract(isodow FROM d) IN (6, 7),
       r, ef, ea, ind, s11, bf,
       (r OR ef OR ea OR ind OR s11 OR bf),
       CASE WHEN ef THEN 'Eid-ul-Fitr' WHEN ea THEN 'Eid-ul-Adha' WHEN r THEN 'Ramadan'
            WHEN ind THEN '14 August' WHEN s11 THEN '11.11' WHEN bf THEN 'Black Friday' ELSE 'Regular day' END
FROM (
    SELECT d,
           (d BETWEEN '2024-03-11' AND '2024-04-09') OR (d BETWEEN '2025-03-01' AND '2025-03-30') AS r,
           (d BETWEEN '2024-04-10' AND '2024-04-12') OR (d BETWEEN '2025-03-31' AND '2025-04-02') AS ef,
           (d BETWEEN '2024-06-17' AND '2024-06-19') OR (d BETWEEN '2025-06-07' AND '2025-06-09') AS ea,
           (extract(month FROM d) = 8 AND extract(day FROM d) = 14) AS ind,
           (extract(month FROM d) = 11 AND extract(day FROM d) = 11) AS s11,
           (d = '2024-11-29') AS bf
    FROM generate_series('2023-01-01'::date, '2026-12-31'::date, '1 day') AS d
) x
ON CONFLICT (date_key) DO UPDATE SET
    is_ramadan = EXCLUDED.is_ramadan, is_eid_ul_fitr = EXCLUDED.is_eid_ul_fitr, is_eid_ul_adha = EXCLUDED.is_eid_ul_adha,
    is_independence_day = EXCLUDED.is_independence_day, is_11_11 = EXCLUDED.is_11_11,
    is_black_friday = EXCLUDED.is_black_friday, is_event_day = EXCLUDED.is_event_day, event_name = EXCLUDED.event_name;

INSERT INTO dw.dim_date (date_key, full_date, day_name, month_name, year_month, quarter, event_name,
                         is_weekend, is_ramadan, is_eid_ul_fitr, is_eid_ul_adha, is_independence_day, is_11_11,
                         is_black_friday, is_event_day)
VALUES (0, NULL, 'Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown', false, false, false, false, false, false, false, false)
ON CONFLICT (date_key) DO NOTHING;

-- ---------------------------------------------------------------- DimLocation
INSERT INTO dw.dim_location (location_key, city_id, city, province, region, population_tier)
VALUES (-1, -1, 'Unknown', 'Unknown', 'Unknown', 'Unknown')
ON CONFLICT (location_key) DO NOTHING;

INSERT INTO dw.dim_location (city_id, city, province, region, population_tier, latitude, longitude)
SELECT city_id, city, province, region, population_tier, latitude, longitude FROM stg.locations
ON CONFLICT (city_id) DO UPDATE SET
    city = EXCLUDED.city, province = EXCLUDED.province, region = EXCLUDED.region,
    population_tier = EXCLUDED.population_tier, latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude;

-- ---------------------------------------------------------------- DimProduct
INSERT INTO dw.dim_product (product_key, product_id, product_name, category, sub_category, brand, price_band)
VALUES (-1, 'UNKNOWN', 'Unknown product', 'Unknown', 'Unknown', 'Unknown', 'Unknown')
ON CONFLICT (product_key) DO NOTHING;

INSERT INTO dw.dim_product (product_id, product_name, category, sub_category, brand, list_price, cost_price, weight_kg, price_band)
SELECT product_id, product_name, category, sub_category, brand, list_price, cost_price, weight_kg,
       CASE WHEN list_price < 1000 THEN '1. < 1k' WHEN list_price < 3000 THEN '2. 1k-3k'
            WHEN list_price < 10000 THEN '3. 3k-10k' ELSE '4. 10k+' END
FROM stg.products
ON CONFLICT (product_id) DO UPDATE SET
    product_name = EXCLUDED.product_name, category = EXCLUDED.category, sub_category = EXCLUDED.sub_category,
    brand = EXCLUDED.brand, list_price = EXCLUDED.list_price, cost_price = EXCLUDED.cost_price,
    weight_kg = EXCLUDED.weight_kg, price_band = EXCLUDED.price_band;

-- ---------------------------------------------------------------- DimSeller (geography denormalised)
INSERT INTO dw.dim_seller (seller_key, seller_id, seller_name, seller_tier, city, province, region, population_tier)
VALUES (-1, 'UNKNOWN', 'Unknown seller', 'Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown')
ON CONFLICT (seller_key) DO NOTHING;

INSERT INTO dw.dim_seller (seller_id, seller_name, join_date, seller_tier, rating, city, province, region, population_tier)
SELECT s.seller_id, s.seller_name, s.join_date, s.seller_tier, s.rating,
       COALESCE(l.city, 'Unknown'), COALESCE(l.province, 'Unknown'), COALESCE(l.region, 'Unknown'),
       COALESCE(l.population_tier, 'Unknown')
FROM stg.sellers s LEFT JOIN stg.locations l ON l.city_id = s.city_id
ON CONFLICT (seller_id) DO UPDATE SET
    seller_name = EXCLUDED.seller_name, join_date = EXCLUDED.join_date, seller_tier = EXCLUDED.seller_tier,
    rating = EXCLUDED.rating, city = EXCLUDED.city, province = EXCLUDED.province, region = EXCLUDED.region,
    population_tier = EXCLUDED.population_tier;

-- ---------------------------------------------------------------- DimCustomer (SCD Type 1)
-- RFM snapshot as of the end of the data window (2025-06-30), non-cancelled orders, NMV.
INSERT INTO dw.dim_customer (customer_key, customer_id, full_name, gender, age_band, city, province, region,
                             population_tier, rfm_segment)
VALUES (-1, 'UNKNOWN', 'Unknown customer', 'Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown')
ON CONFLICT (customer_key) DO NOTHING;

WITH ord AS (
    SELECT o.customer_id, o.order_id, o.order_date,
           SUM(i.quantity * i.unit_price - i.discount_amount) AS nmv
    FROM stg.orders o JOIN stg.order_items i ON i.order_id = o.order_id
    WHERE o.order_status <> 'Cancelled'
    GROUP BY o.customer_id, o.order_id, o.order_date
), rfm AS (
    SELECT customer_id,
           ('2025-06-30'::date - MAX(order_date)) AS recency_days,
           COUNT(*) AS frequency,
           SUM(nmv) AS monetary,
           MIN(order_date) AS first_order_date
    FROM ord GROUP BY customer_id
), scored AS (
    SELECT r.*,
           6 - NTILE(5) OVER (ORDER BY recency_days, customer_id) AS r_score,
           CASE WHEN frequency = 1 THEN 1 WHEN frequency = 2 THEN 2 WHEN frequency <= 4 THEN 3
                WHEN frequency <= 8 THEN 4 ELSE 5 END AS f_score,
           NTILE(5) OVER (ORDER BY monetary, customer_id) AS m_score
    FROM rfm r
), seg AS (
    SELECT s.*,
           CASE WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Champions'
                WHEN r_score >= 3 AND f_score >= 3                  THEN 'Loyal Customers'
                WHEN r_score >= 4 AND f_score = 2                   THEN 'Potential Loyalists'
                WHEN r_score >= 4 AND f_score = 1                   THEN 'New Customers'
                WHEN r_score <= 2 AND f_score >= 3                  THEN 'At Risk'
                WHEN r_score <= 2 AND f_score <= 2                  THEN 'Hibernating'
                ELSE 'Need Attention' END AS segment
    FROM scored s
)
INSERT INTO dw.dim_customer (customer_id, full_name, email, phone, gender, birth_year, age_band, registration_date,
                             city, province, region, population_tier, first_order_date, rfm_recency_days,
                             rfm_frequency, rfm_monetary, rfm_r, rfm_f, rfm_m, rfm_segment, n_source_ids, updated_at)
SELECT c.customer_id, c.full_name, c.email, c.phone, c.gender, c.birth_year,
       CASE WHEN c.birth_year IS NULL THEN 'Unknown'
            WHEN 2025 - c.birth_year < 25 THEN '18-24' WHEN 2025 - c.birth_year < 35 THEN '25-34'
            WHEN 2025 - c.birth_year < 45 THEN '35-44' WHEN 2025 - c.birth_year < 55 THEN '45-54' ELSE '55+' END,
       c.registration_date,
       COALESCE(l.city, 'Unknown'), COALESCE(l.province, 'Unknown'), COALESCE(l.region, 'Unknown'),
       COALESCE(l.population_tier, 'Unknown'),
       s.first_order_date, s.recency_days, COALESCE(s.frequency, 0), COALESCE(s.monetary, 0),
       s.r_score, s.f_score, s.m_score, COALESCE(s.segment, 'No Purchases'), c.n_source_ids, now()
FROM stg.customers c
LEFT JOIN stg.locations l ON l.city_id = c.city_id
LEFT JOIN seg s ON s.customer_id = c.customer_id
ON CONFLICT (customer_id) DO UPDATE SET            -- SCD1: overwrite attributes
    full_name = EXCLUDED.full_name, email = EXCLUDED.email, phone = EXCLUDED.phone, gender = EXCLUDED.gender,
    birth_year = EXCLUDED.birth_year, age_band = EXCLUDED.age_band, registration_date = EXCLUDED.registration_date,
    city = EXCLUDED.city, province = EXCLUDED.province, region = EXCLUDED.region,
    population_tier = EXCLUDED.population_tier, first_order_date = EXCLUDED.first_order_date,
    rfm_recency_days = EXCLUDED.rfm_recency_days, rfm_frequency = EXCLUDED.rfm_frequency,
    rfm_monetary = EXCLUDED.rfm_monetary, rfm_r = EXCLUDED.rfm_r, rfm_f = EXCLUDED.rfm_f, rfm_m = EXCLUDED.rfm_m,
    rfm_segment = EXCLUDED.rfm_segment, n_source_ids = EXCLUDED.n_source_ids, updated_at = now();
