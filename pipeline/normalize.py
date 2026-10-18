"""Reusable parsers and label dictionaries. Label maps are keyed on a
normalised form (lower-case, punctuation stripped) so new spelling variants in
a later data drop still map as long as they reduce to a known key; anything
else becomes 'Unknown' and is counted in the DQ log rather than silently kept."""
import re

import numpy as np
import pandas as pd

WORD_NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%b %d %Y", "%d-%m-%Y", "%Y/%m/%d",
                "%d %b %Y", "%B %d %Y", "%d.%m.%Y"]


def key(s: pd.Series) -> pd.Series:
    """Normalise a label for dictionary lookup."""
    return (s.fillna("").astype(str).str.lower().str.strip()
            .str.replace("&", " and ", regex=False)
            .str.replace(r"[^a-z0-9 ]", " ", regex=True)
            .str.replace(r"\s+", " ", regex=True).str.strip())


def map_labels(s: pd.Series, mapping: dict, unknown="Unknown"):
    """Returns (mapped series, mask of values that were non-empty but unmapped)."""
    k = key(s)
    m = {key(pd.Series([a]))[0]: b for a, b in mapping.items()}
    out = k.map(m)
    unmapped = out.isna() & (k != "")
    return out.fillna(unknown), unmapped


def parse_date(s: pd.Series) -> pd.Series:
    """Parse mixed formats. Slashed dates are day/month/year per the brief."""
    s = s.fillna("").astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        todo = out.isna() & (s != "")
        if not todo.any():
            break
        out.loc[todo] = pd.to_datetime(s[todo], format=fmt, errors="coerce")
    return out


def parse_money(s: pd.Series) -> pd.Series:
    s = (s.fillna("").astype(str).str.strip()
         .str.replace(r"(?i)rs\.?|pkr", "", regex=True)
         .str.replace(",", "", regex=False).str.replace(" ", "", regex=False))
    return pd.to_numeric(s, errors="coerce").astype(float)


def parse_quantity(s: pd.Series) -> pd.Series:
    t = s.fillna("").astype(str).str.strip().str.lower()
    t = t.map(lambda v: WORD_NUMBERS.get(v, v))
    return pd.to_numeric(t, errors="coerce").astype(float)


def normalise_phone(s: pd.Series) -> pd.Series:
    d = s.fillna("").astype(str).str.replace(r"\D", "", regex=True)
    d = d.str.replace(r"^0092", "0", regex=True).str.replace(r"^92(?=3)", "0", regex=True)
    d = np.where(d.str.match(r"^3\d{9}$"), "0" + d, d)
    d = pd.Series(d, index=s.index)
    return d.where(d.str.match(r"^03\d{9}$"), None)


def normalise_email(s: pd.Series) -> pd.Series:
    e = s.fillna("").astype(str).str.strip().str.lower()
    return e.where(e.str.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$"), None)


def title_name(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip().str.replace(r"\s+", " ", regex=True).str.title()


# ---------------------------------------------------------------- dictionaries
PROVINCE = {
    "punjab": "Punjab", "panjab": "Punjab",
    "sindh": "Sindh", "sind": "Sindh",
    "khyber pakhtunkhwa": "Khyber Pakhtunkhwa", "kp": "Khyber Pakhtunkhwa", "kpk": "Khyber Pakhtunkhwa",
    "nwfp": "Khyber Pakhtunkhwa",
    "balochistan": "Balochistan", "baluchistan": "Balochistan",
    "gilgit baltistan": "Gilgit-Baltistan", "gb": "Gilgit-Baltistan",
    "azad kashmir": "Azad Jammu & Kashmir", "azad jammu and kashmir": "Azad Jammu & Kashmir", "ajk": "Azad Jammu & Kashmir",
    "islamabad": "Islamabad Capital Territory", "ict": "Islamabad Capital Territory",
    "islamabad capital territory": "Islamabad Capital Territory",
}
REGION = {"north": "North", "south": "South", "central": "Central", "east": "East", "west": "West"}
POP_TIER = {"metro": "Metro", "tier 1": "Metro", "tier 2": "Tier-2", "tier2": "Tier-2", "tier 3": "Tier-3", "tier3": "Tier-3"}
SELLER_TIER = {"gold": "Gold", "silver": "Silver", "bronze": "Bronze", "platinum": "Platinum"}
GENDER = {"m": "Male", "male": "Male", "f": "Female", "female": "Female"}

CATEGORY = {
    "fashion": "Fashion", "clothing": "Fashion", "fashion and apparel": "Fashion", "apparel": "Fashion",
    "mobile and accessories": "Mobile & Accessories", "mobile acc": "Mobile & Accessories", "mobiles": "Mobile & Accessories",
    "mobile": "Mobile & Accessories",
    "home and kitchen": "Home & Kitchen", "home": "Home & Kitchen", "homeandkitchen": "Home & Kitchen",
    "electronics": "Electronics", "electronic items": "Electronics", "elec": "Electronics",
    "beauty and personal care": "Beauty & Personal Care", "beauty": "Beauty & Personal Care",
    "personal care": "Beauty & Personal Care",
    "footwear": "Footwear", "shoes": "Footwear",
    "grocery": "Grocery", "groceries": "Grocery", "food and grocery": "Grocery",
    "sports and outdoors": "Sports & Outdoors", "sports": "Sports & Outdoors",
    "health and wellness": "Health & Wellness", "health": "Health & Wellness",
    "toys and games": "Toys & Games", "toys": "Toys & Games",
    "books and stationery": "Books & Stationery", "books": "Books & Stationery", "stationary": "Books & Stationery",
    "stationery": "Books & Stationery",
    "automotive": "Automotive", "auto": "Automotive", "car accessories": "Automotive",
}
# sub_category prefix -> category (used to cross-check / fill category)
SUBCAT_PREFIX = {"Fashion": "Fashion", "Mobile": "Mobile & Accessories", "Home": "Home & Kitchen",
                 "Electronics": "Electronics", "Beauty": "Beauty & Personal Care", "Footwear": "Footwear",
                 "Grocery": "Grocery", "Sports": "Sports & Outdoors", "Health": "Health & Wellness",
                 "Toys": "Toys & Games", "Books": "Books & Stationery", "Automotive": "Automotive"}

ORDER_STATUS = {
    "delivered": "Delivered", "deliverd": "Delivered", "complete": "Delivered", "completed": "Delivered",
    "cancelled": "Cancelled", "canceled": "Cancelled", "cancel": "Cancelled",
    "returned": "Returned", "return": "Returned",
    "in transit": "In Transit", "in-transit": "In Transit", "shipped": "In Transit", "intransit": "In Transit",
}
CHANNEL = {"app": "App", "mobile app": "App", "web": "Web", "website": "Web",
           "mobile web": "Mobile Web", "mweb": "Mobile Web", "m web": "Mobile Web"}
PAY_METHOD = {
    "cod": "COD", "cash on delivery": "COD",
    "card": "Card", "credit debit card": "Card", "debit card": "Card", "credit card": "Card",
    "jazzcash": "JazzCash", "jazz cash": "JazzCash",
    "easypaisa": "EasyPaisa", "easy paisa": "EasyPaisa",
    "bank transfer": "Bank Transfer", "bank trf": "Bank Transfer",
}
PAY_STATUS = {"paid": "Paid", "complete": "Paid", "success": "Paid", "completed": "Paid",
              "cancelled": "Cancelled", "canceled": "Cancelled",
              "refunded": "Refunded", "refund": "Refunded", "pending": "Pending"}
COURIER = {"tcs": "TCS", "tcs express": "TCS", "t c s": "TCS",
           "leopards": "Leopards", "leopard courier": "Leopards", "leopard": "Leopards",
           "m and p": "M&P", "mnp": "M&P", "m p": "M&P",
           "trax": "Trax", "postex": "PostEx", "post ex": "PostEx",
           "blueex": "BlueEx", "blue ex": "BlueEx"}
DELIVERY_STATUS = {"delivered": "Delivered", "deliverd": "Delivered", "complete": "Delivered", "completed": "Delivered",
                   "returned to seller": "Returned to Seller", "return to seller": "Returned to Seller",
                   "rto": "Returned to Seller",
                   "in transit": "In Transit", "shipped": "In Transit"}
RETURN_STATUS = {"refunded": "Refunded", "refund": "Refunded", "approved": "Approved",
                 "rejected": "Rejected", "declined": "Rejected"}
RETURN_REASON = {
    "size fit issue": "Size/fit issue", "size issue": "Size/fit issue", "doesn t fit": "Size/fit issue",
    "size fit": "Size/fit issue", "wrong size": "Size/fit issue",
    "not as described": "Not as described", "different from picture": "Not as described",
    "quality issue": "Quality issue", "poor quality": "Quality issue", "bad quality": "Quality issue",
    "quality": "Quality issue",
    "damaged product": "Damaged product", "damaged": "Damaged product", "item damaged": "Damaged product",
    "changed mind": "Changed mind", "change of mind": "Changed mind", "no longer needed": "Changed mind",
    "changed my mind": "Changed mind",
    "wrong item delivered": "Wrong item delivered", "wrong item": "Wrong item delivered",
    "received wrong product": "Wrong item delivered",
    "colour mismatch": "Colour mismatch", "color mismatch": "Colour mismatch", "colour different": "Colour mismatch",
    "wrong colour": "Colour mismatch", "wrong color": "Colour mismatch",
    "late delivery": "Late delivery", "delivered late": "Late delivery", "too late": "Late delivery",
    "late": "Late delivery",
    "missing parts": "Missing parts", "parts missing": "Missing parts", "missing part": "Missing parts",
    "incomplete": "Missing parts",
}
