# NexusMart – Data Quality Report

Generated from the pipeline's own logs (`data/work/dq/dq_log.csv`, `data/work/rejects/`). Every number below was produced by code in `pipeline/clean.py`; nothing was edited by hand. Unrepairable records are kept in reject files (and in `dq.rejects` in the database) with a reason code – nothing is silently deleted.

## 1. Before / after row counts

| table | raw_rows | clean_rows | rejected_rows | removed_as_duplicates_or_merged |
|---|---|---|---|---|
| locations | 650 | 650 | 0 | 0 |
| sellers | 420 | 420 | 0 | 0 |
| products | 3,200 | 3,144 | 0 | 56 |
| customers | 45,000 | 42,500 | 0 | 2,500 |
| orders | 163,200 | 159,899 | 101 | 3,200 |
| order_items | 315,143 | 314,909 | 234 | 0 |
| payments | 168,111 | 164,815 | 0 | 3,296 |
| shipping | 151,228 | 151,186 | 42 | 0 |
| returns | 16,048 | 15,906 | 142 | 0 |

*`removed_as_duplicates_or_merged`* = exact duplicate rows removed (orders 3,200; payments 3,296) or duplicate entities merged into a master record (customers 2,500; products 56 – the mapping tables `customer_id_map.csv` / `product_id_map.csv` keep every original ID so all related records still link).

## 2. Raw profile (validate_raw)

| file | rows | exact_duplicates | pk_conflicts |
|---|---|---|---|
| customers | 45,000 | 0 | 0 |
| products | 3,200 | 0 | 0 |
| sellers | 420 | 0 | 0 |
| locations | 650 | 0 | 0 |
| orders | 163,200 | 3,200 | 0 |
| order_items | 315,143 | 0 | 0 |
| payments | 168,111 | 3,296 | 0 |
| shipping | 151,228 | 0 | 0 |
| returns | 16,048 | 0 | 0 |

Blank-value counts per column are stored in `data/work/dq/raw_validation.json`.

## 3. Rejected records by reason

| source_table | reject_reason | rows |
|---|---|---|
| order_items | ORDER_NOT_FOUND_OR_REJECTED | 223 |
| order_items | QTY_OR_PRICE_UNREPAIRABLE | 11 |
| orders | INVALID_ORDER_DATE_UNREPAIRABLE | 100 |
| orders | ORDER_HAS_NO_VALID_LINES | 1 |
| returns | ORDER_ITEM_NOT_FOUND | 142 |
| shipping | ORDER_NOT_FOUND_OR_REJECTED | 42 |

## 4. Every cleaning rule applied (with rows affected)

Rules with 0 affected rows are kept in the log (they guard against the next data drop) but omitted here.

### locations

| column | issue | action | rows_affected | note |
|---|---|---|---|---|
| province | inconsistent spellings (Panjab, PUNJAB, KPK, Sind...) | standardised to 7 canonical names | 105 |  |
| latitude/longitude | latitude and longitude swapped | swapped back | 6 |  |
| latitude/longitude | outside Pakistan bounding box | set NULL | 2 |  |
| latitude/longitude | missing coordinates | retained as NULL (not used in metrics) | 63 |  |
| province | missing province | imputed from nearest city in same region (coordinates) | 25 |  |

### sellers

| column | issue | action | rows_affected | note |
|---|---|---|---|---|
| seller_name | leading/trailing whitespace | trimmed | 15 |  |
| seller_tier | case/whitespace variants (BRONZE, 'Gold ') | standardised | 64 |  |
| seller_tier | missing tier | set 'Unknown' (cannot be derived) | 22 |  |
| join_date | mixed date formats | parsed to DATE | 58 |  |
| join_date | missing join date | retained NULL | 38 |  |
| rating | rating outside 1-5 | set NULL | 22 |  |
| rating | missing rating | retained NULL (excluded from averages) | 55 |  |

### products

| column | issue | action | rows_affected | note |
|---|---|---|---|---|
| category | 62 raw spellings of category | mapped to 12 canonical categories | 1,339 |  |
| sub_category | missing sub_category | set 'Unspecified' | 485 |  |
| brand | missing brand | imputed from first word of product_name (known brand list) | 392 |  |
| list_price | text formatted price ('Rs. 1,250') | parsed to numeric | 105 |  |
| list_price | negative price | absolute value taken (sign error) | 4 |  |
| list_price | placeholder/implausible price (9,999,999, 0) | replaced with median observed selling price | 9 |  |
| weight_kg | weight > 100 kg (entered in grams) | divided by 1000 | 7 |  |
| weight_kg | zero/negative weight | set NULL | 10 |  |
| weight_kg | missing weight | retained NULL (not used in metrics) | 306 |  |
| product_id | same product under different IDs | merged to lowest ID; mapping table kept | 56 | match on name+brand+weight+price, not name alone |
| cost_price | cost >= list price (implausible, ~1.5x list) | re-imputed | 67 |  |
| cost_price | missing cost | imputed | 170 |  |
| cost_price | cost imputed | from duplicate partner (7) else category median cost/list ratio (230) | 237 |  |

### customers

| column | issue | action | rows_affected | note |
|---|---|---|---|---|
| email | upper-case / whitespace | lower-cased & trimmed | 1,466 |  |
| email | missing/invalid email | retained NULL | 1,698 |  |
| phone | 5 phone formats (+92, dashes, spaces) | standardised to 03XXXXXXXXX | 26,871 |  |
| phone | missing/invalid phone | retained NULL | 3,599 |  |
| gender | 9 variants (m, male, F...) | mapped to Male/Female | 42,801 |  |
| gender | missing gender | set 'Unknown' | 2,199 |  |
| registration_date | mixed formats (dd/mm/yyyy, 'Mon d yyyy') | parsed | 6,913 |  |
| birth_year | implausible birth year (outside (1930, 2010)) | set NULL | 142 |  |
| birth_year | missing birth year | retained NULL | 4,742 |  |
| customer_id | same customer under different IDs | merged to lowest ID; mapping table kept | 2,500 | email/phone match + same name + <=1 attribute conflict; 61 candidate pairs NOT merged |
| city_id | missing/invalid city | imputed from customer's most frequent ship city | 1,473 |  |
| city_id | no city derivable | LocationKey Unknown | 513 |  |

### orders

| column | issue | action | rows_affected | note |
|---|---|---|---|---|
| * | exact duplicate rows | removed (kept first occurrence) | 3,200 |  |
| order_status | 19 raw labels (DELIVERD, Complete, Canceled...) | mapped to Delivered/Cancelled/Returned/In Transit | 38,750 |  |
| channel | 12 raw labels (APP, MWeb, Website...) | mapped to App/Web/Mobile Web | 23,830 |  |
| discount_code | case/whitespace variants (save20, ' SAVE15') | upper-cased & trimmed | 4,005 |  |
| order_date | mixed formats (yyyy-mm-dd, dd/mm/yyyy, 'Mon d yyyy') | parsed | 23,949 |  |
| order_date | invalid date (1124 unparseable e.g. 31/02, 481 outside Jan-2024..Jun-2025) | repaired from first payment date, else shipped_date-1 | 1,505 |  |
| * | unrepairable record | rejected (INVALID_ORDER_DATE_UNREPAIRABLE) | 100 |  |
| customer_id | order points to a duplicate customer ID | re-pointed to master ID | 3,582 |  |
| customer_id | customer ID not in customers file (C9xxxx) | kept; CustomerKey = Unknown | 321 |  |
| ship_city_id | missing ship city | imputed from customer's registered city (matches 89% of the time) | 6,080 |  |
| ship_city_id | missing ship city and customer city | LocationKey = Unknown | 306 |  |
| order_total | source total inconsistent with lines (9,999,999, negatives, 0) | replaced with sum of repaired line net values | 531 |  |
| * | unrepairable record | rejected (ORDER_HAS_NO_VALID_LINES) | 1 |  |

### order_items

| column | issue | action | rows_affected | note |
|---|---|---|---|---|
| * | unrepairable record | rejected (ORDER_NOT_FOUND_OR_REJECTED) | 223 |  |
| product_id | line points to duplicate product ID | re-pointed to master ID | 5,514 |  |
| product_id | product ID not in catalogue (P9xxxx) | kept; ProductKey = Unknown, cost imputed | 932 |  |
| quantity | quantity as words ('two') or decimals ('2.0') | converted to integer | 5,763 |  |
| quantity | negative quantity | absolute value (sign error) | 307 |  |
| quantity | implausible quantity (0, >20; 500 seen) | flagged for repair from order_total | 641 |  |
| unit_price | text formatted price ('Rs. 2,290') | parsed | 7,995 |  |
| unit_price | negative price | absolute value | 312 |  |
| unit_price | price 100x reference (entered in paisa) | divided by 100 | 298 |  |
| unit_price | price 1/280 of reference (entered in USD) | multiplied by 280 | 308 |  |
| unit_price | placeholder/zero/implausible price (9,999,999, 0) | flagged for repair | 650 |  |
| unit_price | corrupt price | solved exactly from order_total | 633 |  |
| quantity | corrupt quantity | solved exactly from order_total | 630 |  |
| unit_price | corrupt price not solvable from order_total | imputed with product's median price that month | 17 |  |
| * | unrepairable record | rejected (QTY_OR_PRICE_UNREPAIRABLE) | 11 |  |
| discount_amount | missing discount amount | recomputed from order discount_code % | 31,546 |  |
| discount_amount | discount inconsistent with code (e.g. 130% of gross, /100) | recomputed from order discount_code % | 881 |  |
| unit_cost | no catalogue cost (unknown product) | unit_price x global median cost ratio 0.604 | 932 |  |

### payments

| column | issue | action | rows_affected | note |
|---|---|---|---|---|
| * | exact duplicate rows | removed (kept first occurrence) | 3,296 |  |
| payment_method | 21 raw labels | mapped to COD/Card/JazzCash/EasyPaisa/Bank Transfer | 36,004 |  |
| payment_status | 16 raw labels (Success, Complete, PAID) | mapped to Paid/Cancelled/Refunded/Pending | 40,782 |  |
| amount | negative amount | absolute value | 663 |  |
| amount | placeholder amount (>= 1,000,000) | set NULL (not used in revenue metrics) | 162 |  |
| payment_date | missing/invalid payment date | retained NULL | 5,994 |  |

### shipping

| column | issue | action | rows_affected | note |
|---|---|---|---|---|
| * | unrepairable record | rejected (ORDER_NOT_FOUND_OR_REJECTED) | 42 |  |
| courier | 22 raw labels (T.C.S, MnP, Blue-Ex...) | mapped to 6 couriers | 30,359 |  |
| delivery_status | raw label variants (RTO, DELIVERD) | mapped to Delivered/Returned to Seller/In Transit | 37,687 |  |
| shipped/delivered_date | delivered before shipped | dates swapped (entry order error) | 1,269 |  |
| delivered_date | transit > 30 days (cluster at 88-102 days) | delivered_date set NULL; excluded from delivery-time metrics | 266 |  |
| shipped_date | shipped before order date | flagged; ShippingDays measured ship->deliver | 1,036 |  |
| shipped_date | missing shipped date | retained NULL | 6,924 |  |
| delivered_date | missing delivered date (in transit / RTO / gaps) | retained NULL | 20,026 |  |
| shipping_fee | negative fee | absolute value | 159 |  |
| shipping_fee | missing/zero/placeholder fee (> 10,000) | imputed with courier median fee | 9,437 |  |

### returns

| column | issue | action | rows_affected | note |
|---|---|---|---|---|
| * | unrepairable record | rejected (ORDER_ITEM_NOT_FOUND) | 142 |  |
| return_status | case variants, 'Declined', 'Refund' | mapped to Refunded/Approved/Rejected | 3,964 |  |
| return_reason | 38 raw reasons | mapped to 9 canonical reasons | 7,172 |  |
| return_reason | missing reason | set 'Not specified' | 2,367 |  |
| return_date | return dated before order | flagged | 121 |  |
| refund_amount | rejected return with refund | refund set to 0 | 25 |  |
| refund_amount | refund > line net value (~1.4x) | capped at line net value | 230 |  |

## 5. Missing-value decisions (impute / flag / retain / quarantine)

| Column | Decision | Business reason |
|---|---|---|
| orders.order_date (invalid) | Repair from first prepaid payment date (matches order date 98.4% of the time), else shipped date − 1 day; else quarantine | Revenue must be dated to land in a month; a guessed date would distort trends |
| orders.ship_city_id | Impute from customer's registered city (equal in 88.7% of orders), else Unknown | Geography analysis needs a location; flagged with `ship_city_imputed` |
| customers.city_id | Impute from the customer's most frequent ship city, else Unknown | Same entity, more reliable source |
| order_items.discount_amount | Recompute from order discount code % (consistent on 99.4% of lines) | The code is the authoritative order-level discount per the brief |
| order_items.unit_price / quantity (corrupt) | Solve exactly from order_total = Σ(qty×price)×(1−disc%) when it is the only bad field; else product's median price that month; else quarantine | order_total is an independent source of truth for the line |
| products.cost_price (missing or ≥ list price) | Duplicate partner's cost, else list price × category median cost/list ratio; flagged `cost_imputed` | Needed for COGS/margin; category ratio is the least-biased estimate |
| products.brand | First word of product name when it is a known brand | Names are built as '<Brand> <Item> <Code>' |
| products.sub_category | 'Unspecified' | Tier (Basics/Premium/Essentials) cannot be derived |
| shipping.shipping_fee (missing/0/placeholder) | Courier median fee; flagged `fee_imputed` | Fee is a real NexusMart cost; dropping it would overstate profit |
| returns.refund_amount (> line value) | Capped at line net value | A refund cannot exceed what was paid |
| returns.return_reason | 'Not specified' | Kept in rates; reason unknown |
| customers.gender / birth_year / seller rating / tier | Retain as Unknown / NULL | Descriptive only; imputing would invent attributes |
| lat/long, weight_kg | Retain NULL | Not used in any metric |
