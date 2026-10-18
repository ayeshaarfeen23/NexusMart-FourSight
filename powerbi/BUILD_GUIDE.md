# Power BI build guide (NexusMart)

The dashboard must connect to the **warehouse**, not the CSVs, and pre-built templates are not allowed, so the
`.pbix` is built by hand in Power BI Desktop from this guide. Plan on about 2–3 hours.

## 1. Connect
1. Start the stack (`docker compose up -d`) and let the DAG finish (or run `python scripts/run_pipeline.py`).
2. Power BI Desktop → **Get data → PostgreSQL database**
   Server `localhost:5433`, Database `nexusmart_dw`, mode **Import**. User `nexus`, password `nexus`.
   (If Power BI asks for the Npgsql provider, install it, or tick "Encrypt connections" off in the data source settings.)
3. Select: `dw.fact_sales`, `dw.dim_date`, `dw.dim_customer`, `dw.dim_product`, `dw.dim_seller`, `dw.dim_location`,
   `mart.v_seller_scorecard`. Rename them to drop the schema prefix (e.g. `fact_sales`, `seller_scorecard`).
4. In Power Query on `dim_date`, filter `date_key <> 0` (removes the Unknown row so the table can be marked as a date table).
   This is a filter on a loaded table only. All cleaning is already done in Python, which keeps you within the rule that core cleaning must not happen in Power Query.

## 2. Model (star schema)
| From (many) | To (one) | Active |
|---|---|---|
| fact_sales[date_key] | dim_date[date_key] | ✔ |
| fact_sales[return_date_key] | dim_date[date_key] | inactive (used by `USERELATIONSHIP`) |
| fact_sales[customer_key] | dim_customer[customer_key] | ✔ |
| fact_sales[product_key] | dim_product[product_key] | ✔ |
| fact_sales[seller_key] | dim_seller[seller_key] | ✔ |
| fact_sales[location_key] | dim_location[location_key] | ✔ |
| seller_scorecard[seller_key] | dim_seller[seller_key] | ✔ (1:1, single direction from dim_seller) |

* Mark `dim_date` as a date table on `full_date`.
* Sort `dim_date[month_name]` by `month_num`; `year_month` is already sortable text.
* Hide all key columns and the flag columns that are used only by measures.
* Create an empty table `_Measures` and paste every measure from `measures.dax`.
* Format: Net Revenue, NMV, Gross, Margin, COGS as **PKR, 0 decimals, display units Millions**. Rates as %, 2 decimals.
* View → Themes → Browse → `nexusmart_theme.json`.

## 3. Pages (one layout grid: KPI cards on top, slicer pane on the left)
Put these **slicers on every page** with *Sync slicers*: `dim_date[full_date]` (between), `dim_product[category]`,
`dim_location[region]`, `dim_seller[seller_tier]`, `dim_customer[rfm_segment]`.

### 1 · Executive Overview
* Cards: Net Revenue, Orders, AOV, Units, Return Rate, Cancellation Rate, Active Customers. Each card has a subtitle
  measure showing MoM % or MoM (pp) for rates (`Net Revenue MoM %` and so on).
* Line + column combo: Net Revenue (columns) & Margin % (line) by `year_month`.
* Waterfall: Gross Sales → cancellations → discounts → refunds → COGS → shipping → margin after shipping
  (build with a small disconnected table of step names + SWITCH measure, or use the stacked bar alternative).
* Text box with the 3 key takeaways (from the executive summary).

### 2 · Time Analysis
* Line chart: Net Revenue and `Net Revenue 3M Avg` by month. Add a weekly view with a drill-down hierarchy
  Year → Month → week_start.
* Column chart: `Net Revenue MoM %` by month (conditional colours: green when positive, red when negative).
* Clustered bar: `Festival Uplift %`, Return Rate and Cancellation Rate by `dim_date[event_name]`.
* Matrix: year_month × day_name heat-map of Avg Daily Net Revenue.

### 3 · Product & Category
* Bar: Net Revenue and Margin % by category (sorted). Scatter: category Net Revenue (x) vs Margin % (y), size = Units.
* Table: Top 10 and Bottom 10 products (Top N filter on `Product Revenue Rank`).
* Scatter: product NMV (x) vs Return Rate (y), so the high-sales and high-return products in the top-right are easy to spot.
  Tooltip: seller_name.

### 4 · Geography
* Filled map or Azure map: Net Revenue by province / city (lat/long from dim_location).
* Bar: top 10 and bottom 10 cities. Card: `Top 5 City Share`.
* Donut: revenue share by region. Matrix: population_tier × region (Net Revenue, AOV, Return Rate).

### 5 · Customer Analysis
* Cards: Active, New, Returning Customers, Repeat Purchase Rate, Observed CLV.
* Bar: Net Revenue and customer count by `rfm_segment`.
* Line: New vs Returning customers by month.
* Cohort matrix: rows = first_order_date month (add a calculated column `Cohort = FORMAT(dim_customer[first_order_date],"yyyy-mm")`),
  columns = year_month, values = Active Customers.
* Table: top 20 customers by Net Revenue.

### 6 · Seller Performance
* Table from `seller_scorecard` + dim_seller: rank, name, tier, quality score, net revenue, return rate, on-time, cancel rate
  (data bars on the score).
* Clustered column: seller_tier × (Return Rate, On-Time Rate, Avg Delivery Days, revenue per seller).
* Scatter: quality score vs net revenue.

### 7 · Returns & Cancellations
* Line: Return Rate and Cancellation Rate by month.
* Bars: Return Rate by category, by seller (Top N) and by region. Bar: Cancellation Rate by payment_method.
* Bar: returns by return_reason. Line: refunds by return date (`Refunds by Return Date`).
* Column: Return Rate by delivery-days bucket (create a group on `delivery_days`: 0-3, 4-5, 6-7, 8-10, 11+).

## 4. Interactivity requirements
* **Drill-through page** "Seller detail": drill-through field `dim_seller[seller_name]`; show KPIs, monthly trend, product table.
  Do the same for "Product detail" on `dim_product[product_name]`.
* **Drill-down**: date hierarchy (Year → Quarter → Month → Day) on the trend visuals; Region → Province → City on geography.
* **Tooltip page** (Page size: Tooltip): Net Revenue, Margin %, Return Rate, Orders; assign it to category and city visuals.
* **Bookmarks**: on Executive Overview, add a toggle between a "Revenue view" and a "Profit view" (margin visuals), plus a
  "Reset filters" bookmark button.

## 5. Check the dashboard against the warehouse (with no slicers applied)
| KPI | Expected |
|---|---|
| Net Revenue | 1,142,380,640 |
| NMV | 1,199,981,658 |
| Gross Sales | 1,436,547,056 |
| Orders (non-cancelled) | 145,297 |
| AOV | 8,258.82 |
| Units | 469,634 |
| Return Rate | 5.15 % |
| Cancellation Rate | 9.13 % |
| Margin | 304,949,967 (26.69 %) |

## 6. Export
File → Export → **PDF** (all pages) → `reports/dashboard_export.pdf`; save the file as `powerbi/NexusMart.pbix`.
