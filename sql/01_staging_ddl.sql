-- =====================================================================
-- 01  Schemas, staging and data-quality tables (idempotent)
--     stg : cleaned records exactly as produced by pipeline/clean.py
--     dq  : data-quality log, reject table, row counts, check results
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS dq;
CREATE SCHEMA IF NOT EXISTS dw;
CREATE SCHEMA IF NOT EXISTS mart;

CREATE TABLE IF NOT EXISTS stg.locations (
    city_id INT PRIMARY KEY, city TEXT, province TEXT, region TEXT,
    latitude NUMERIC(9,4), longitude NUMERIC(9,4), population_tier TEXT);

CREATE TABLE IF NOT EXISTS stg.sellers (
    seller_id TEXT PRIMARY KEY, seller_name TEXT, join_date DATE, seller_tier TEXT,
    city_id INT, rating NUMERIC(3,1));

CREATE TABLE IF NOT EXISTS stg.products (
    product_id TEXT PRIMARY KEY, product_name TEXT, category TEXT, sub_category TEXT, brand TEXT,
    list_price NUMERIC(14,2), cost_price NUMERIC(14,2), cost_imputed SMALLINT, weight_kg NUMERIC(8,3), seller_id TEXT);

CREATE TABLE IF NOT EXISTS stg.product_id_map (
    product_id TEXT PRIMARY KEY, master_product_id TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS stg.customers (
    customer_id TEXT PRIMARY KEY, full_name TEXT, email TEXT, phone TEXT, gender TEXT,
    registration_date DATE, city_id INT, birth_year INT, n_source_ids INT, city_imputed SMALLINT);

CREATE TABLE IF NOT EXISTS stg.customer_id_map (
    customer_id TEXT PRIMARY KEY, master_customer_id TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS stg.orders (
    order_id TEXT PRIMARY KEY, customer_id TEXT, customer_known SMALLINT, order_date DATE NOT NULL,
    order_date_repaired SMALLINT, order_status TEXT, ship_city_id INT, ship_city_imputed SMALLINT,
    source_order_total NUMERIC(14,2), discount_code TEXT, discount_pct NUMERIC(5,2), channel TEXT,
    order_total NUMERIC(14,2), payment_method TEXT, is_split_payment SMALLINT);

CREATE TABLE IF NOT EXISTS stg.order_items (
    order_item_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, product_id TEXT, product_known SMALLINT,
    seller_id TEXT, quantity INT, unit_price NUMERIC(14,2), discount_amount NUMERIC(14,2),
    price_repaired SMALLINT, qty_repaired SMALLINT, discount_repaired SMALLINT, unit_cost NUMERIC(14,2));

CREATE TABLE IF NOT EXISTS stg.payments (
    payment_id TEXT PRIMARY KEY, order_id TEXT, payment_method TEXT, payment_status TEXT,
    amount NUMERIC(14,2), payment_date DATE);

CREATE TABLE IF NOT EXISTS stg.shipping (
    shipment_id TEXT PRIMARY KEY, order_id TEXT UNIQUE, courier TEXT, shipped_date DATE, delivered_date DATE,
    shipping_fee NUMERIC(12,2), fee_imputed SMALLINT, delivered_date_invalid SMALLINT, delivery_status TEXT);

CREATE TABLE IF NOT EXISTS stg.returns (
    return_id TEXT PRIMARY KEY, order_item_id TEXT, return_date DATE, return_reason TEXT,
    return_status TEXT, refund_amount NUMERIC(14,2), is_valid_return SMALLINT);

-- ---------------------------------------------------------------- dq
CREATE TABLE IF NOT EXISTS dq.dq_log (
    run_id TEXT, table_name TEXT, column_name TEXT, issue TEXT, action TEXT, rows_affected INT, note TEXT);

CREATE TABLE IF NOT EXISTS dq.rejects (
    run_id TEXT, source_table TEXT, source_key TEXT, reject_reason TEXT, record_json TEXT);

CREATE TABLE IF NOT EXISTS dq.row_counts (
    run_id TEXT, table_name TEXT, raw_rows INT, clean_rows INT, rejected_rows INT);

CREATE TABLE IF NOT EXISTS dq.task_log (
    run_id TEXT, task TEXT, logged_at TIMESTAMP DEFAULT now(), rows_read INT, rows_rejected INT, rows_loaded INT, note TEXT);

CREATE TABLE IF NOT EXISTS dq.quality_results (
    run_id TEXT, check_name TEXT, severity TEXT, passed BOOLEAN, observed TEXT, expected TEXT,
    checked_at TIMESTAMP DEFAULT now());
