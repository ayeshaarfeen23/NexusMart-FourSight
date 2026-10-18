"""Profiling-driven cleaning of the nine NexusMart files.

Every rule below is implemented in code, logs its row count to the DQ log, and
any record that cannot be repaired goes to data/work/rejects/<table>_rejects.csv
with a reason code. Nothing is silently dropped.

Output: data/work/clean/<table>.csv  (+ customer_id_map.csv, product_id_map.csv)
"""
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from . import normalize as N
from .dq import DQ

log = logging.getLogger("nexusmart.clean")


def _read(raw_dir, name):
    return pd.read_csv(Path(raw_dir) / f"{name}.csv", dtype=str, keep_default_na=False)


def _blank(s):
    return s.fillna("").astype(str).str.strip() == ""


def _strip_all(df):
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    return df


def _dedupe_exact(df, table, dq):
    n = len(df)
    df = df.drop_duplicates()
    dq.event(table, "*", "exact duplicate rows", "removed (kept first occurrence)", n - len(df))
    return df


# =========================================================================== locations
def clean_locations(raw, dq):
    df = _strip_all(raw.copy())
    t = "locations"
    dq.set_count(t, "raw", len(df))
    df = _dedupe_exact(df, t, dq)

    df["city_id"] = pd.to_numeric(df.city_id, errors="coerce")
    bad = df.city_id.isna()
    dq.reject(t, raw.loc[df.index[bad]], "INVALID_CITY_ID")
    df = df[~bad].copy()
    df["city_id"] = df.city_id.astype(int)

    prov, unm = N.map_labels(df.province, N.PROVINCE)
    dq.event(t, "province", "inconsistent spellings (Panjab, PUNJAB, KPK, Sind...)", "standardised to 7 canonical names",
             (prov != df.province).sum() - _blank(df.province).sum())
    dq.event(t, "province", "unrecognised label", "set Unknown", unm.sum())
    df["province"] = prov

    df["region"], _ = N.map_labels(df.region, N.REGION)
    df["population_tier"], _ = N.map_labels(df.population_tier, N.POP_TIER)

    lat = pd.to_numeric(df.latitude, errors="coerce")
    lon = pd.to_numeric(df.longitude, errors="coerce")
    swap = (lat > 40) & (lon < 40)       # Pakistan: lat 23-37, lon 60-78
    lat2 = lat.where(~swap, lon)
    lon2 = lon.where(~swap, lat)
    dq.event(t, "latitude/longitude", "latitude and longitude swapped", "swapped back", swap.sum())
    out_rng = ~lat2.between(23, 37.5) | ~lon2.between(60, 78)
    out_rng &= lat2.notna() & lon2.notna()
    lat2[out_rng] = np.nan
    lon2[out_rng] = np.nan
    dq.event(t, "latitude/longitude", "outside Pakistan bounding box", "set NULL", out_rng.sum())
    dq.event(t, "latitude/longitude", "missing coordinates", "retained as NULL (not used in metrics)",
             (lat2.isna() | lon2.isna()).sum())
    df["latitude"], df["longitude"] = lat2, lon2

    # Missing province -> nearest city with a known province (same region), by coordinates
    miss = df.province == "Unknown"
    known = df[~miss & df.latitude.notna()]
    filled = 0
    for idx, r in df[miss].iterrows():
        cand = known[known.region == r.region] if r.region != "Unknown" else known
        if pd.isna(r.latitude) or cand.empty:
            continue
        d = (cand.latitude - r.latitude) ** 2 + (cand.longitude - r.longitude) ** 2
        df.at[idx, "province"] = cand.loc[d.idxmin(), "province"]
        filled += 1
    dq.event(t, "province", "missing province", "imputed from nearest city in same region (coordinates)", filled)
    dq.event(t, "province", "missing province and coordinates", "kept as 'Unknown'", (df.province == "Unknown").sum())

    df["city"] = df.city.str.strip()
    dq.set_count(t, "clean", len(df))
    return df[["city_id", "city", "province", "region", "latitude", "longitude", "population_tier"]]


# =========================================================================== sellers
def clean_sellers(raw, loc, dq):
    t = "sellers"
    df = _strip_all(raw.copy())
    dq.set_count(t, "raw", len(df))
    df = _dedupe_exact(df, t, dq)
    dq.event(t, "seller_name", "leading/trailing whitespace", "trimmed", (raw.seller_name != raw.seller_name.str.strip()).sum())

    tier, unm = N.map_labels(df.seller_tier, N.SELLER_TIER)
    dq.event(t, "seller_tier", "case/whitespace variants (BRONZE, 'Gold ')", "standardised",
             ((tier != df.seller_tier) & ~_blank(df.seller_tier)).sum())
    dq.event(t, "seller_tier", "missing tier", "set 'Unknown' (cannot be derived)", _blank(df.seller_tier).sum())
    df["seller_tier"] = tier

    jd = N.parse_date(df.join_date)
    dq.event(t, "join_date", "mixed date formats", "parsed to DATE", (~df.join_date.str.match(r"^\d{4}-\d{2}-\d{2}$") & jd.notna()).sum())
    dq.event(t, "join_date", "missing join date", "retained NULL", jd.isna().sum())
    df["join_date"] = jd.dt.date

    r = pd.to_numeric(df.rating, errors="coerce")
    badr = r.notna() & ~r.between(1, 5)
    r[badr] = np.nan
    dq.event(t, "rating", "rating outside 1-5", "set NULL", badr.sum())
    dq.event(t, "rating", "missing rating", "retained NULL (excluded from averages)", r.isna().sum())
    df["rating"] = r

    cid = pd.to_numeric(df.city_id, errors="coerce")
    badc = cid.isna() | ~cid.isin(loc.city_id)
    dq.event(t, "city_id", "missing/unknown city", "mapped to Unknown location (-1)", badc.sum())
    df["city_id"] = cid.where(~badc, -1).astype(int)
    dq.set_count(t, "clean", len(df))
    return df[["seller_id", "seller_name", "join_date", "seller_tier", "city_id", "rating"]]


# =========================================================================== products
def clean_products(raw, sellers, oi_raw, dq):
    t = "products"
    df = _strip_all(raw.copy())
    dq.set_count(t, "raw", len(df))
    df = _dedupe_exact(df, t, dq)

    # ---- category
    cat, unm = N.map_labels(df.category, N.CATEGORY)
    changed = (cat != df.category)
    dq.event(t, "category", f"{df.category.nunique()} raw spellings of category", "mapped to 12 canonical categories", changed.sum())
    sub = df.sub_category.replace("", np.nan)
    sub_cat = sub.str.split().str[0].map(N.SUBCAT_PREFIX)
    fill = (cat == "Unknown") & sub_cat.notna()
    cat[fill] = sub_cat[fill]
    dq.event(t, "category", "category unrecognised but sub_category known", "category taken from sub_category prefix", fill.sum())
    conflict = sub_cat.notna() & (cat != sub_cat)
    dq.event(t, "category", "category conflicts with sub_category prefix", "kept category; flagged", conflict.sum())
    df["category"] = cat
    dq.event(t, "sub_category", "missing sub_category", "set 'Unspecified'", sub.isna().sum())
    df["sub_category"] = sub.fillna("Unspecified")

    # ---- brand: product names start with the brand
    known_brands = set(df.brand[df.brand != ""])
    first = df.product_name.str.split().str[0]
    first_norm = first.str.lower().map({b.lower(): b for b in known_brands})
    miss = df.brand == ""
    df.loc[miss, "brand"] = first_norm[miss]
    dq.event(t, "brand", "missing brand", "imputed from first word of product_name (known brand list)", (miss & first_norm.notna()).sum())
    df["brand"] = df.brand.fillna("Unknown")

    # ---- reference price observed in orders (robust median per product)
    up = N.parse_money(oi_raw.unit_price)
    ok = up.between(50, C.MONEY_SENTINEL - 1)
    obs = up[ok].groupby(oi_raw.product_id[ok]).median()

    # ---- list price
    lp = N.parse_money(df.list_price)
    fmt = df.list_price.str.contains(r"[^\d.\-]", regex=True)
    dq.event(t, "list_price", "text formatted price ('Rs. 1,250')", "parsed to numeric", fmt.sum())
    neg = lp < 0
    lp[neg] = lp[neg].abs()
    dq.event(t, "list_price", "negative price", "absolute value taken (sign error)", neg.sum())
    obs_p = df.product_id.map(obs)
    bad = lp.isna() | (lp >= C.MONEY_SENTINEL) | (lp < 10)
    ratio = lp / obs_p
    bad |= obs_p.notna() & ~ratio.between(0.5, 2.0)
    lp[bad] = obs_p[bad].round()
    dq.event(t, "list_price", "placeholder/implausible price (9,999,999, 0)", "replaced with median observed selling price", (bad & obs_p.notna()).sum())
    df["list_price"] = lp

    # ---- weight
    w = pd.to_numeric(df.weight_kg, errors="coerce")
    grams = w > 100
    w[grams] = w[grams] / 1000
    dq.event(t, "weight_kg", "weight > 100 kg (entered in grams)", "divided by 1000", grams.sum())
    nonpos = w <= 0
    w[nonpos] = np.nan
    dq.event(t, "weight_kg", "zero/negative weight", "set NULL", nonpos.sum())
    dq.event(t, "weight_kg", "missing weight", "retained NULL (not used in metrics)", w.isna().sum())
    df["weight_kg"] = w

    # ---- duplicate products under different IDs ----------------------------------
    # Match rule (not name alone): same normalised name (case, year suffix removed)
    # AND same brand when both known AND weight equal when both known AND list price within 10%.
    df["_nn"] = (df.product_name.str.lower().str.replace(r"\s*\(\d{4}\)\s*$", "", regex=True)
                 .str.replace(r"\s+", " ", regex=True).str.strip())
    df["_num"] = df.product_id.str.extract(r"(\d+)")[0].astype(int)
    df = df.sort_values("_num")
    master = {}
    for _, g in df[df._nn.duplicated(keep=False)].groupby("_nn"):
        g = g.sort_values("_num")
        m = g.iloc[0]
        for _, r in g.iloc[1:].iterrows():
            same_brand = (r.brand == m.brand) or "Unknown" in (r.brand, m.brand)
            same_w = pd.isna(r.weight_kg) or pd.isna(m.weight_kg) or abs(r.weight_kg - m.weight_kg) < 0.011
            close_p = abs(r.list_price - m.list_price) <= 0.10 * max(m.list_price, 1)
            if same_brand and same_w and close_p:
                master[r.product_id] = m.product_id
    pmap = pd.DataFrame({"product_id": df.product_id, "master_product_id": df.product_id.map(master).fillna(df.product_id)})
    dq.event(t, "product_id", "same product under different IDs", "merged to lowest ID; mapping table kept", len(master),
             "match on name+brand+weight+price, not name alone")

    # ---- cost price (after dup detection so partner cost can be used)
    cp = N.parse_money(df.cost_price)
    over = cp.notna() & (cp >= df.list_price)
    dq.event(t, "cost_price", "cost >= list price (implausible, ~1.5x list)", "re-imputed", over.sum())
    missing = cp.isna()
    dq.event(t, "cost_price", "missing cost", "imputed", missing.sum())
    cp[over] = np.nan
    # partner cost first
    partner = {}
    for dup, m in master.items():
        partner.setdefault(dup, m)
        partner.setdefault(m, dup)
    pc = df.product_id.map(partner).map(pd.Series(cp.values, index=df.product_id.values))
    use_p = cp.isna() & pc.notna()
    cp[use_p] = pc[use_p]
    ratio = (cp / df.list_price).groupby(df.category).median()
    imp = cp.isna()
    cp[imp] = (df.list_price[imp] * df.category[imp].map(ratio)).round()
    dq.event(t, "cost_price", "cost imputed", f"from duplicate partner ({use_p.sum()}) else category median cost/list ratio ({imp.sum()})",
             use_p.sum() + imp.sum())
    df["cost_price"] = cp
    df["cost_imputed"] = (over | missing).astype(int)

    sid_bad = ~df.seller_id.isin(sellers.seller_id)
    dq.event(t, "seller_id", "seller not in sellers file", "kept; seller attributes Unknown", sid_bad.sum())

    # dimension keeps only master records; duplicates live on in product_id_map
    df = df[~df.product_id.isin(list(master))].sort_values("_num")
    dq.set_count(t, "clean", len(df))
    df["product_name"] = df.product_name.str.replace(r"\s+", " ", regex=True)
    cols = ["product_id", "product_name", "category", "sub_category", "brand", "list_price", "cost_price",
            "cost_imputed", "weight_kg", "seller_id"]
    return df[cols], pmap


# =========================================================================== customers
def clean_customers(raw, loc, dq):
    t = "customers"
    df = _strip_all(raw.copy())
    dq.set_count(t, "raw", len(df))
    df = _dedupe_exact(df, t, dq)

    df["full_name"] = N.title_name(df.full_name)
    em = N.normalise_email(df.email)
    dq.event(t, "email", "upper-case / whitespace", "lower-cased & trimmed", (df.email != df.email.str.strip().str.lower()).sum())
    dq.event(t, "email", "missing/invalid email", "retained NULL", em.isna().sum())
    ph = N.normalise_phone(df.phone)
    dq.event(t, "phone", "5 phone formats (+92, dashes, spaces)", "standardised to 03XXXXXXXXX",
             (ph.notna() & (ph != df.phone)).sum())
    dq.event(t, "phone", "missing/invalid phone", "retained NULL", ph.isna().sum())
    df["email"], df["phone"] = em, ph

    g, unm = N.map_labels(df.gender, N.GENDER)
    dq.event(t, "gender", "9 variants (m, male, F...)", "mapped to Male/Female", (~_blank(df.gender)).sum())
    dq.event(t, "gender", "missing gender", "set 'Unknown'", _blank(df.gender).sum())
    df["gender"] = g

    rd = N.parse_date(df.registration_date)
    dq.event(t, "registration_date", "mixed formats (dd/mm/yyyy, 'Mon d yyyy')", "parsed",
             (~df.registration_date.str.match(r"^\d{4}-\d{2}-\d{2}$")).sum())
    df["registration_date"] = rd

    by = pd.to_numeric(df.birth_year, errors="coerce")
    bad = by.notna() & ~by.between(*C.BIRTH_YEAR_RANGE)
    dq.event(t, "birth_year", f"implausible birth year (outside {C.BIRTH_YEAR_RANGE})", "set NULL", bad.sum())
    by[bad] = np.nan
    dq.event(t, "birth_year", "missing birth year", "retained NULL", by.isna().sum())
    df["birth_year"] = by.astype("Int64")

    cid = pd.to_numeric(df.city_id, errors="coerce")
    df["city_id"] = cid.where(cid.isin(loc.city_id)).astype("Int64")

    # ---- duplicate customers ------------------------------------------------------
    # Candidate pairs share a normalised email OR phone. They are merged only if the
    # normalised name is identical AND at most one of {other contact, birth_year, city}
    # conflicts (both present and different). Same-name customers with different
    # contacts are NOT merged (name alone is never a match).
    df["_num"] = df.customer_id.str.extract(r"(\d+)")[0].astype(int)
    df = df.sort_values("_num").reset_index(drop=True)
    parent = list(range(len(df)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    nm = df.full_name.str.lower()
    pairs = 0
    rejected_pairs = 0
    for keycol, other in (("email", "phone"), ("phone", "email")):
        sub = df[df[keycol].notna()]
        for _, idx in sub.groupby(keycol).groups.items():
            idx = list(idx)
            if len(idx) < 2:
                continue
            a = idx[0]
            for b in idx[1:]:
                if nm[a] != nm[b]:
                    rejected_pairs += 1
                    continue
                conflicts = 0
                for col in (other, "birth_year", "city_id"):
                    va, vb = df.at[a, col], df.at[b, col]
                    if pd.notna(va) and pd.notna(vb) and va != vb:
                        conflicts += 1
                if conflicts <= 1:
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
                        pairs += 1
                else:
                    rejected_pairs += 1
    root = [find(i) for i in range(len(df))]
    df["master_customer_id"] = df.customer_id.values[root]
    cmap = df[["customer_id", "master_customer_id"]].copy()
    n_merged = (df.customer_id != df.master_customer_id).sum()
    dq.event(t, "customer_id", "same customer under different IDs", "merged to lowest ID; mapping table kept", n_merged,
             f"email/phone match + same name + <=1 attribute conflict; {rejected_pairs} candidate pairs NOT merged")

    # Survivor record: master's values, gaps filled from duplicates; earliest registration
    agg = df.sort_values("_num").groupby("master_customer_id").agg(
        full_name=("full_name", "first"), email=("email", "first"), phone=("phone", "first"),
        gender=("gender", lambda s: next((v for v in s if v != "Unknown"), "Unknown")),
        registration_date=("registration_date", "min"), city_id=("city_id", "first"),
        birth_year=("birth_year", "first"), n_source_ids=("customer_id", "count"),
    ).reset_index().rename(columns={"master_customer_id": "customer_id"})
    dq.set_count(t, "clean", len(agg))
    return agg, cmap


# =========================================================================== orders
def clean_orders(raw, cmap, customers, loc, pay_first_date, ship_dates, dq):
    t = "orders"
    df = _strip_all(raw.copy())
    dq.set_count(t, "raw", len(df))
    df = _dedupe_exact(df, t, dq)
    iddup = df.order_id.duplicated()
    dq.reject(t, df[iddup], "DUPLICATE_ORDER_ID_CONFLICTING")
    df = df[~iddup].copy()

    st, unm = N.map_labels(df.order_status, N.ORDER_STATUS)
    dq.event(t, "order_status", f"{df.order_status.nunique()} raw labels (DELIVERD, Complete, Canceled...)",
             "mapped to Delivered/Cancelled/Returned/In Transit", (st != df.order_status).sum())
    dq.event(t, "order_status", "unrecognised status", "set 'Unknown'", unm.sum())
    df["order_status"] = st

    ch, unm = N.map_labels(df.channel, N.CHANNEL)
    dq.event(t, "channel", "12 raw labels (APP, MWeb, Website...)", "mapped to App/Web/Mobile Web", (ch != df.channel).sum())
    df["channel"] = ch

    code = df.discount_code.str.strip().str.upper()
    dq.event(t, "discount_code", "case/whitespace variants (save20, ' SAVE15')", "upper-cased & trimmed", (code != df.discount_code).sum())
    pct = pd.to_numeric(code.str.extract(r"(\d+)")[0], errors="coerce")
    badc = (code != "") & (pct.isna() | ~pct.between(0, 90))
    dq.event(t, "discount_code", "unparseable code", "treated as no discount", badc.sum())
    df["discount_code"] = code.where(code != "", None)
    df["discount_pct"] = pct.where(~badc, 0).fillna(0)

    # ---- order date
    od = N.parse_date(df.order_date)
    dq.event(t, "order_date", "mixed formats (yyyy-mm-dd, dd/mm/yyyy, 'Mon d yyyy')", "parsed",
             (~df.order_date.str.match(r"^\d{4}-\d{2}-\d{2}$") & od.notna()).sum())
    lo, hi = pd.Timestamp(C.ORDER_DATE_MIN), pd.Timestamp(C.ORDER_DATE_MAX)
    invalid = od.isna() | (od < lo) | (od > hi)
    n_unparse = od.isna().sum()
    # Repair from related records: payment date (prepaid orders are paid on the order date)
    # else shipped date - 1 day (median ship lag is 1 day).
    pdte = df.order_id.map(pay_first_date)
    sdte = df.order_id.map(ship_dates)
    cand = pdte.where(pdte.notna(), sdte - pd.Timedelta(days=1))
    rep = invalid & cand.notna() & cand.between(lo, hi)
    od[rep] = cand[rep]
    df["order_date_repaired"] = rep.astype(int)
    dq.event(t, "order_date", f"invalid date ({n_unparse} unparseable e.g. 31/02, {invalid.sum() - n_unparse} outside Jan-2024..Jun-2025)",
             "repaired from first payment date, else shipped_date-1", rep.sum())
    still = invalid & ~rep
    dq.reject(t, df[still], "INVALID_ORDER_DATE_UNREPAIRABLE")
    df = df[~still].copy()
    df["order_date"] = od[~still].dt.date

    # ---- customer
    cm = dict(zip(cmap.customer_id, cmap.master_customer_id))
    remapped = df.customer_id.map(cm)
    dq.event(t, "customer_id", "order points to a duplicate customer ID", "re-pointed to master ID",
             (remapped.notna() & (remapped != df.customer_id)).sum())
    unknown = remapped.isna()
    dq.event(t, "customer_id", "customer ID not in customers file (C9xxxx)", "kept; CustomerKey = Unknown", unknown.sum())
    df["customer_id"] = remapped.fillna(df.customer_id)
    df["customer_known"] = (~unknown).astype(int)

    # ---- ship city
    sc = pd.to_numeric(df.ship_city_id, errors="coerce")
    sc = sc.where(sc.isin(loc.city_id))
    cust_city = df.customer_id.map(customers.set_index("customer_id").city_id)
    fill = sc.isna() & cust_city.notna()
    dq.event(t, "ship_city_id", "missing ship city", "imputed from customer's registered city (matches 89% of the time)", fill.sum())
    sc[fill] = cust_city[fill]
    dq.event(t, "ship_city_id", "missing ship city and customer city", "LocationKey = Unknown", sc.isna().sum())
    df["ship_city_id"] = sc.astype("Int64")
    df["ship_city_imputed"] = fill.astype(int)

    df["source_order_total"] = N.parse_money(df.order_total)
    dq.set_count(t, "clean", len(df))
    return df[["order_id", "customer_id", "customer_known", "order_date", "order_date_repaired", "order_status",
               "ship_city_id", "ship_city_imputed", "source_order_total", "discount_code", "discount_pct", "channel"]]


# =========================================================================== order_items
def clean_order_items(raw, orders, pmap, products, sellers, dq):
    t = "order_items"
    df = _strip_all(raw.copy())
    dq.set_count(t, "raw", len(df))
    df = _dedupe_exact(df, t, dq)
    dup = df.order_item_id.duplicated()
    dq.reject(t, df[dup], "DUPLICATE_ORDER_ITEM_ID")
    df = df[~dup].copy()

    orphan = ~df.order_id.isin(orders.order_id)
    dq.reject(t, df[orphan], "ORDER_NOT_FOUND_OR_REJECTED")
    df = df[~orphan].copy()
    src = df.copy()

    # ---- product mapping
    pm = dict(zip(pmap.product_id, pmap.master_product_id))
    mp = df.product_id.map(pm)
    dq.event(t, "product_id", "line points to duplicate product ID", "re-pointed to master ID",
             (mp.notna() & (mp != df.product_id)).sum())
    unk = mp.isna()
    dq.event(t, "product_id", "product ID not in catalogue (P9xxxx)", "kept; ProductKey = Unknown, cost imputed", unk.sum())
    df["product_id"] = mp.fillna(df.product_id)
    df["product_known"] = (~unk).astype(int)
    sbad = ~df.seller_id.isin(sellers.seller_id)
    dq.event(t, "seller_id", "seller not in sellers file", "SellerKey = Unknown", sbad.sum())

    # ---- quantity
    q = N.parse_quantity(df.quantity)
    words = df.quantity.str.match(r"^[A-Za-z]+$")
    dq.event(t, "quantity", "quantity as words ('two') or decimals ('2.0')", "converted to integer",
             (words | df.quantity.str.contains(r"\.")).sum())
    neg = q < 0
    q[neg] = q[neg].abs()
    dq.event(t, "quantity", "negative quantity", "absolute value (sign error)", neg.sum())
    q_bad = q.isna() | (q == 0) | (q > C.MAX_QTY)
    dq.event(t, "quantity", f"implausible quantity (0, >{C.MAX_QTY}; 500 seen)", "flagged for repair from order_total", q_bad.sum())

    # ---- unit price
    up = N.parse_money(df.unit_price)
    dq.event(t, "unit_price", "text formatted price ('Rs. 2,290')", "parsed", df.unit_price.str.contains("Rs", case=False).sum())
    od = df.order_id.map(orders.set_index("order_id").order_date)
    month = pd.to_datetime(od).dt.to_period("M")
    # Reference price: median of plausible prices for the product in the same month, else overall
    plaus = up.between(50, C.MONEY_SENTINEL - 1)
    base = up[plaus].groupby(df.product_id[plaus]).median()
    r0 = up / df.product_id.map(base)
    clean_mask = plaus & r0.between(*C.PRICE_OK_BAND)
    ref_m = up[clean_mask].groupby([df.product_id[clean_mask], month[clean_mask]]).median()
    ref = pd.Series(list(zip(df.product_id, month)), index=df.index).map(ref_m)
    ref = ref.fillna(df.product_id.map(base))
    r = up / ref
    fix_neg = (up < 0) & (-r).between(*C.PRICE_OK_BAND)
    up[fix_neg] = -up[fix_neg]
    dq.event(t, "unit_price", "negative price", "absolute value", fix_neg.sum())
    r = up / ref
    x100 = r.between(*C.PRICE_X100_BAND)
    up[x100] = (up[x100] / 100).round(2)
    dq.event(t, "unit_price", "price 100x reference (entered in paisa)", "divided by 100", x100.sum())
    usd = (r * C.PRICE_USD_FACTOR).between(*C.PRICE_OK_BAND) & (up < 1000)
    up[usd] = (up[usd] * C.PRICE_USD_FACTOR).round()
    dq.event(t, "unit_price", f"price 1/{C.PRICE_USD_FACTOR} of reference (entered in USD)", f"multiplied by {C.PRICE_USD_FACTOR}", usd.sum())
    r = up / ref
    p_bad = up.isna() | (up <= 0) | (up >= C.MONEY_SENTINEL) | (ref.notna() & ~r.between(0.5, 2.0))
    dq.event(t, "unit_price", "placeholder/zero/implausible price (9,999,999, 0)", "flagged for repair", p_bad.sum())

    # ---- solve the single corrupt field of an order from the order_total -------------
    # order_total = sum(qty*price) * (1 - discount_pct) (holds for 99.6% of clean orders)
    o = orders.set_index("order_id")
    pct = df.order_id.map(o.discount_pct) / 100
    tot = df.order_id.map(o.source_order_total)
    tot_ok = tot.between(1, C.MONEY_SENTINEL - 1)
    gross_target = tot / (1 - pct)
    good_line = ~(q_bad | p_bad)
    gross_good = (q * up).where(good_line, 0).groupby(df.order_id).transform("sum")
    n_bad = (~good_line).groupby(df.order_id).transform("sum")
    solvable = (~good_line) & (n_bad == 1) & tot_ok & ~(q_bad & p_bad)
    resid = gross_target - gross_good
    # price corrupt -> price = resid / qty ; qty corrupt -> qty = resid / price
    sp = solvable & p_bad
    new_p = (resid / q).round(2)
    okp = sp & (new_p > 0) & (ref.isna() | (new_p / ref).between(0.5, 2.0))
    up[okp] = new_p[okp]
    sq = solvable & q_bad
    new_q = (resid / up).round()
    okq = sq & (new_q >= 1) & (new_q <= C.MAX_QTY) & (abs(new_q * up - resid) <= 0.02 * resid.abs() + 2)
    q[okq] = new_q[okq]
    dq.event(t, "unit_price", "corrupt price", "solved exactly from order_total", okp.sum())
    dq.event(t, "quantity", "corrupt quantity", "solved exactly from order_total", okq.sum())
    # remaining price issues -> product reference price for that month
    p_left = p_bad & ~okp & ref.notna()
    up[p_left] = ref[p_left].round()
    dq.event(t, "unit_price", "corrupt price not solvable from order_total", "imputed with product's median price that month", p_left.sum())
    q_left = q_bad & ~okq
    p_unfixable = p_bad & ~okp & ref.isna()
    rej = q_left | p_unfixable
    df["quantity"], df["unit_price"] = q, up
    df["price_repaired"] = (p_bad | x100 | usd | fix_neg).astype(int)
    df["qty_repaired"] = (q_bad | neg).astype(int)
    dq.reject(t, src[rej], "QTY_OR_PRICE_UNREPAIRABLE")
    df = df[~rej].copy()
    pct = pct[~rej]

    # ---- discount: the order-level code is authoritative (matches 99.4% of lines)
    disc_src = pd.to_numeric(df.discount_amount, errors="coerce")
    disc = (df.quantity * df.unit_price * pct).round(2)
    miss = disc_src.isna()
    wrong = ~miss & ((disc_src - disc).abs() > 1)
    dq.event(t, "discount_amount", "missing discount amount", "recomputed from order discount_code %", miss.sum())
    dq.event(t, "discount_amount", "discount inconsistent with code (e.g. 130% of gross, /100)", "recomputed from order discount_code %",
             wrong.sum())
    df["discount_amount"] = disc
    df["discount_repaired"] = (miss | wrong).astype(int)

    df["quantity"] = df.quantity.astype(int)
    dq.set_count(t, "clean", len(df))
    return df[["order_item_id", "order_id", "product_id", "product_known", "seller_id", "quantity", "unit_price",
               "discount_amount", "price_repaired", "qty_repaired", "discount_repaired"]]


# =========================================================================== payments
def clean_payments(raw, dq):
    t = "payments"
    df = _strip_all(raw.copy())
    dq.set_count(t, "raw", len(df))
    df = _dedupe_exact(df, t, dq)
    dup = df.payment_id.duplicated()
    dq.reject(t, df[dup], "DUPLICATE_PAYMENT_ID")
    df = df[~dup].copy()
    m, unm = N.map_labels(df.payment_method, N.PAY_METHOD)
    dq.event(t, "payment_method", f"{df.payment_method.nunique()} raw labels", "mapped to COD/Card/JazzCash/EasyPaisa/Bank Transfer",
             (m != df.payment_method).sum())
    df["payment_method"] = m
    s, unm = N.map_labels(df.payment_status, N.PAY_STATUS)
    dq.event(t, "payment_status", f"{df.payment_status.nunique()} raw labels (Success, Complete, PAID)", "mapped to Paid/Cancelled/Refunded/Pending",
             (s != df.payment_status).sum())
    df["payment_status"] = s
    a = N.parse_money(df.amount)
    neg = a < 0
    a[neg] = a[neg].abs()
    dq.event(t, "amount", "negative amount", "absolute value", neg.sum())
    big = a >= C.MONEY_SENTINEL
    a[big] = np.nan
    dq.event(t, "amount", "placeholder amount (>= 1,000,000)", "set NULL (not used in revenue metrics)", big.sum())
    df["amount"] = a
    d = N.parse_date(df.payment_date)
    dq.event(t, "payment_date", "missing/invalid payment date", "retained NULL", d.isna().sum())
    df["payment_date"] = d.dt.date
    dq.set_count(t, "clean", len(df))
    return df[["payment_id", "order_id", "payment_method", "payment_status", "amount", "payment_date"]]


def order_payment_method(pay):
    """One payment method per order: method of the largest payment (split payments
    exist for ~3% of orders)."""
    p = pay.copy()
    p["_a"] = p.amount.fillna(0)
    p = p.sort_values(["order_id", "_a"], ascending=[True, False])
    first = p.groupby("order_id").first()
    n = p.groupby("order_id").payment_method.nunique()
    return pd.DataFrame({"payment_method": first.payment_method, "is_split_payment": (p.groupby("order_id").size() > 1).astype(int),
                         "n_methods": n})


# =========================================================================== shipping
def clean_shipping(raw, orders, dq):
    t = "shipping"
    df = _strip_all(raw.copy())
    dq.set_count(t, "raw", len(df))
    df = _dedupe_exact(df, t, dq)
    orphan = ~df.order_id.isin(orders.order_id)
    dq.reject(t, df[orphan], "ORDER_NOT_FOUND_OR_REJECTED")
    df = df[~orphan].copy()
    dup = df.order_id.duplicated()
    dq.reject(t, df[dup], "SECOND_SHIPMENT_FOR_ORDER")
    df = df[~dup].copy()

    c, unm = N.map_labels(df.courier, N.COURIER)
    dq.event(t, "courier", f"{df.courier.nunique()} raw labels (T.C.S, MnP, Blue-Ex...)", "mapped to 6 couriers", (c != df.courier).sum())
    df["courier"] = c
    s, unm = N.map_labels(df.delivery_status, N.DELIVERY_STATUS)
    dq.event(t, "delivery_status", "raw label variants (RTO, DELIVERD)", "mapped to Delivered/Returned to Seller/In Transit",
             (s != df.delivery_status).sum())
    df["delivery_status"] = s

    sd, dd = N.parse_date(df.shipped_date), N.parse_date(df.delivered_date)
    swap = sd.notna() & dd.notna() & (dd < sd)
    sd2 = sd.where(~swap, dd)
    dd2 = dd.where(~swap, sd)
    dq.event(t, "shipped/delivered_date", "delivered before shipped", "dates swapped (entry order error)", swap.sum())
    long = sd2.notna() & dd2.notna() & ((dd2 - sd2).dt.days > C.MAX_TRANSIT_DAYS)
    dd2[long] = pd.NaT
    df["delivered_date_invalid"] = long.astype(int)
    dq.event(t, "delivered_date", f"transit > {C.MAX_TRANSIT_DAYS} days (cluster at 88-102 days)", "delivered_date set NULL; excluded from delivery-time metrics", long.sum())
    od = pd.to_datetime(df.order_id.map(orders.set_index("order_id").order_date))
    before = sd2.notna() & (sd2 < od)
    dq.event(t, "shipped_date", "shipped before order date", "flagged; ShippingDays measured ship->deliver", before.sum())
    dq.event(t, "shipped_date", "missing shipped date", "retained NULL", sd2.isna().sum())
    dq.event(t, "delivered_date", "missing delivered date (in transit / RTO / gaps)", "retained NULL", dd2.isna().sum())
    df["shipped_date"], df["delivered_date"] = sd2.dt.date, dd2.dt.date

    fee = N.parse_money(df.shipping_fee)
    neg = fee < 0
    fee[neg] = fee[neg].abs()
    dq.event(t, "shipping_fee", "negative fee", "absolute value", neg.sum())
    bad = fee.isna() | (fee == 0) | (fee > C.MAX_SHIPPING_FEE)
    dq.event(t, "shipping_fee", f"missing/zero/placeholder fee (> {C.MAX_SHIPPING_FEE:,})", "imputed with courier median fee", bad.sum())
    med = fee[~bad].groupby(df.courier[~bad]).median()
    fee[bad] = df.courier[bad].map(med).fillna(fee[~bad].median())
    df["shipping_fee"] = fee
    df["fee_imputed"] = bad.astype(int)
    dq.set_count(t, "clean", len(df))
    return df[["shipment_id", "order_id", "courier", "shipped_date", "delivered_date", "shipping_fee", "fee_imputed",
               "delivered_date_invalid", "delivery_status"]]


# =========================================================================== returns
def clean_returns(raw, items, orders, dq):
    t = "returns"
    df = _strip_all(raw.copy())
    dq.set_count(t, "raw", len(df))
    df = _dedupe_exact(df, t, dq)
    orphan = ~df.order_item_id.isin(items.order_item_id)
    dq.reject(t, df[orphan], "ORDER_ITEM_NOT_FOUND")
    df = df[~orphan].copy()

    s, unm = N.map_labels(df.return_status, N.RETURN_STATUS)
    dq.event(t, "return_status", "case variants, 'Declined', 'Refund'", "mapped to Refunded/Approved/Rejected", (s != df.return_status).sum())
    df["return_status"] = s
    rr, unm = N.map_labels(df.return_reason, N.RETURN_REASON)
    dq.event(t, "return_reason", f"{df.return_reason.nunique()} raw reasons", "mapped to 9 canonical reasons", (rr != df.return_reason).sum())
    dq.event(t, "return_reason", "missing reason", "set 'Not specified'", _blank(df.return_reason).sum())
    rr[_blank(df.return_reason)] = "Not specified"
    dq.event(t, "return_reason", "unrecognised reason", "set 'Other'", unm.sum())
    rr[unm] = "Other"
    df["return_reason"] = rr

    rd = N.parse_date(df.return_date)
    it = items.set_index("order_item_id")
    o = orders.set_index("order_id")
    oid = df.order_item_id.map(it.order_id)
    od = pd.to_datetime(oid.map(o.order_date))
    before = rd.notna() & (rd < od)
    dq.event(t, "return_date", "return dated before order", "flagged", before.sum())
    df["return_date"] = rd.dt.date

    cancelled = oid.map(o.order_status) == "Cancelled"
    dq.reject(t, df[cancelled], "RETURN_ON_CANCELLED_ORDER")
    df = df[~cancelled].copy()
    line_net = (it.quantity * it.unit_price - it.discount_amount)
    net = df.order_item_id.map(line_net)
    rf = N.parse_money(df.refund_amount)
    neg = rf < 0
    rf[neg] = rf[neg].abs()
    rej = df.return_status == "Rejected"
    nz = rej & (rf > 0)
    rf[rej] = 0
    dq.event(t, "refund_amount", "rejected return with refund", "refund set to 0", nz.sum())
    over = ~rej & (rf > net + 1)
    rf[over] = net[over].round(2)
    dq.event(t, "refund_amount", "refund > line net value (~1.4x)", "capped at line net value", over.sum())
    miss = ~rej & rf.isna()
    rf[miss] = net[miss].round(2)
    dq.event(t, "refund_amount", "missing refund on valid return", "set to line net value", miss.sum())
    df["refund_amount"] = rf
    df["is_valid_return"] = (~rej).astype(int)
    dq.set_count(t, "clean", len(df))
    return df[["return_id", "order_item_id", "return_date", "return_reason", "return_status", "refund_amount", "is_valid_return"]]


# =========================================================================== driver
def run(raw_dir=None, work_dir=None):
    raw_dir = Path(raw_dir or C.RAW_DIR)
    work_dir = Path(work_dir or C.WORK_DIR)
    out = work_dir / "clean"
    out.mkdir(parents=True, exist_ok=True)
    dq = DQ(work_dir)
    R = {n: _read(raw_dir, n) for n in C.REQUIRED_COLUMNS}

    loc = clean_locations(R["locations"], dq)
    sel = clean_sellers(R["sellers"], loc, dq)
    prod, pmap = clean_products(R["products"], sel, R["order_items"], dq)
    cust, cmap = clean_customers(R["customers"], loc, dq)
    pay = clean_payments(R["payments"], dq)

    # dates from related tables for order-date repair
    pp = pay.copy()
    pp["payment_date"] = pd.to_datetime(pp.payment_date)
    prepaid = pp[pp.payment_method != "COD"]
    pay_first = prepaid.groupby("order_id").payment_date.min()
    sh_raw = R["shipping"]
    ship_d = pd.Series(N.parse_date(sh_raw.shipped_date).values, index=sh_raw.order_id.str.strip())
    ship_d = ship_d[~ship_d.index.duplicated()]

    orders = clean_orders(R["orders"], cmap, cust, loc, pay_first, ship_d, dq)

    # customers with no valid city -> most frequent ship city of their orders
    miss = cust.city_id.isna()
    mode_city = orders[orders.ship_city_imputed == 0].dropna(subset=["ship_city_id"]).groupby("customer_id").ship_city_id.agg(
        lambda s: s.mode().iloc[0])
    fill = miss & cust.customer_id.map(mode_city).notna()
    cust.loc[fill, "city_id"] = cust.customer_id[fill].map(mode_city)
    cust["city_imputed"] = fill.astype(int)
    dq.event("customers", "city_id", "missing/invalid city", "imputed from customer's most frequent ship city", fill.sum())
    dq.event("customers", "city_id", "no city derivable", "LocationKey Unknown", cust.city_id.isna().sum())

    items = clean_order_items(R["order_items"], orders, pmap, prod, sel, dq)
    # unknown-product lines need a cost basis: global median cost/price ratio
    ratio = (prod.cost_price / prod.list_price).median()
    items["unit_cost"] = items.product_id.map(prod.set_index("product_id").cost_price)
    unk = items.unit_cost.isna()
    items.loc[unk, "unit_cost"] = (items.unit_price[unk] * ratio).round(2)
    dq.event("order_items", "unit_cost", "no catalogue cost (unknown product)", f"unit_price x global median cost ratio {ratio:.3f}", unk.sum())

    # orders: recompute total from repaired lines and compare with source
    g = items.assign(net=items.quantity * items.unit_price - items.discount_amount).groupby("order_id").net.sum()
    orders["order_total"] = orders.order_id.map(g).round(2)
    diff = (orders.source_order_total - orders.order_total).abs() > 2
    dq.event("orders", "order_total", "source total inconsistent with lines (9,999,999, negatives, 0)",
             "replaced with sum of repaired line net values", diff.sum())
    no_lines = orders.order_total.isna()
    dq.reject("orders", orders[no_lines], "ORDER_HAS_NO_VALID_LINES")
    orders = orders[~no_lines].copy()
    dq.set_count("orders", "clean", len(orders))

    pm = order_payment_method(pay)
    orders = orders.merge(pm[["payment_method", "is_split_payment"]], left_on="order_id", right_index=True, how="left")
    dq.event("orders", "payment_method", "order without payment record", "set 'Unknown'", orders.payment_method.isna().sum())
    orders["payment_method"] = orders.payment_method.fillna("Unknown")
    orders["is_split_payment"] = orders.is_split_payment.fillna(0).astype(int)

    ship = clean_shipping(R["shipping"], orders, dq)
    ret = clean_returns(R["returns"], items, orders, dq)

    # write
    for name, df in [("locations", loc), ("sellers", sel), ("products", prod), ("customers", cust), ("orders", orders),
                     ("order_items", items), ("payments", pay), ("shipping", ship), ("returns", ret),
                     ("customer_id_map", cmap), ("product_id_map", pmap)]:
        df.to_csv(out / f"{name}.csv", index=False)
    counts = dq.write()
    rej_rate = dq.counts.get("order_items", {}).get("rejected", 0) / max(dq.counts["order_items"]["raw"], 1)
    log.info("order line reject rate %.3f%%", 100 * rej_rate)
    if rej_rate > C.REJECT_RATE_FAIL:
        raise RuntimeError(f"Reject rate {rej_rate:.2%} exceeds threshold {C.REJECT_RATE_FAIL:.0%}")
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(run())
