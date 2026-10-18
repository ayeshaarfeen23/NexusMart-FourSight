"""Central configuration. Everything comes from environment variables (set in
docker-compose / .env, or Airflow Variables mapped to env), never hard-coded."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = Path(os.getenv("NEXUS_RAW_DIR", ROOT / "data" / "raw"))
WORK_DIR = Path(os.getenv("NEXUS_WORK_DIR", ROOT / "data" / "work"))
SQL_DIR = Path(os.getenv("NEXUS_SQL_DIR", ROOT / "sql"))
REPORT_DIR = Path(os.getenv("NEXUS_REPORT_DIR", ROOT / "reports"))

DB = {
    "host": os.getenv("NEXUS_DB_HOST", "localhost"),
    "port": int(os.getenv("NEXUS_DB_PORT", "5432")),
    "dbname": os.getenv("NEXUS_DB_NAME", "nexusmart_dw"),
    "user": os.getenv("NEXUS_DB_USER", "nexus"),
    "password": os.getenv("NEXUS_DB_PASSWORD", "nexus"),
}

# Business window from the brief
ORDER_DATE_MIN = "2024-01-01"
ORDER_DATE_MAX = "2025-06-30"

# Input contract: file -> required columns (validate_raw fails if any is missing)
REQUIRED_COLUMNS = {
    "customers": ["customer_id", "full_name", "email", "phone", "gender", "registration_date", "city_id", "birth_year"],
    "products": ["product_id", "product_name", "category", "sub_category", "brand", "list_price", "cost_price", "weight_kg", "seller_id"],
    "sellers": ["seller_id", "seller_name", "join_date", "seller_tier", "city_id", "rating"],
    "locations": ["city_id", "city", "province", "region", "latitude", "longitude", "population_tier"],
    "orders": ["order_id", "customer_id", "order_date", "order_status", "ship_city_id", "order_total", "discount_code", "channel"],
    "order_items": ["order_item_id", "order_id", "product_id", "seller_id", "quantity", "unit_price", "discount_amount"],
    "payments": ["payment_id", "order_id", "payment_method", "payment_status", "amount", "payment_date"],
    "shipping": ["shipment_id", "order_id", "courier", "shipped_date", "delivered_date", "shipping_fee", "delivery_status"],
    "returns": ["return_id", "order_item_id", "return_date", "return_reason", "return_status", "refund_amount"],
}

# ---- Documented thresholds (see README "Cleaning rules") -------------------
MONEY_SENTINEL = 1_000_000          # any single price/fee >= this is a placeholder (9,999,999 etc.)
PRICE_OK_BAND = (0.80, 1.25)        # unit_price / reference price accepted as-is
PRICE_X100_BAND = (80, 125)         # unit_price entered in paisa (x100)
PRICE_USD_FACTOR = 280              # unit_price entered in USD (PKR/280)
MAX_QTY = 20                        # quantity above this per line is implausible (500 seen)
MAX_SHIPPING_FEE = 10_000           # courier fee above this is implausible
MAX_TRANSIT_DAYS = 30               # ship->deliver above this is implausible (88-102 day cluster seen)
BIRTH_YEAR_RANGE = (1930, 2010)
REJECT_RATE_FAIL = 0.05             # fail pipeline if >5% of order lines are rejected

# Quality thresholds used by quality_checks (pipeline fails if violated)
QC_MAX_UNKNOWN_SHARE = 0.02         # max share of fact rows on Unknown customer/product/location
