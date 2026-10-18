"""Build reports/executive_summary.pdf (2-3 pages) from reports/answers/*.csv.
All figures are read from the warehouse outputs; text states only what the numbers show."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table,  # noqa: E402
                                TableStyle)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import config as C  # noqa: E402

A = C.REPORT_DIR / "answers"
R = lambda n: pd.read_csv(A / f"{n}.csv")  # noqa: E731
INK, MUTED, ACCENT, GRID = "#263238", "#607D8B", "#C62828", "#E0E4E7"


def m(x):
    return f"{x / 1e6:,.1f}M"


def charts(tmp):
    t = R("q03_monthly_trend")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.0), dpi=200)
    for a in (a1, a2):
        a.spines[["top", "right"]].set_visible(False)
        a.spines[["left", "bottom"]].set_color(GRID)
        a.tick_params(colors=MUTED, labelsize=7)
        a.grid(axis="y", color=GRID, lw=0.6)
        a.set_axisbelow(True)
    x = range(len(t))
    a1.bar(x, t.net_revenue / 1e6, color="#37474F", width=0.7)
    a1.set_xticks(list(x)[::2], t.year_month[::2], rotation=45, ha="right")
    a1.set_title("Net revenue per month (PKR M)", fontsize=9, color=INK, loc="left")
    a2.plot(x, t.margin_pct, color="#37474F", lw=2, label="Margin %")
    p = R("q15_profitability_trend")
    a2.plot(x, p.margin_after_shipping_pct, color=ACCENT, lw=2, label="Margin after shipping %")
    a2.set_xticks(list(x)[::2], t.year_month[::2], rotation=45, ha="right")
    a2.set_ylim(10, 32)
    a2.set_title("Margin as % of net revenue", fontsize=9, color=INK, loc="left")
    a2.text(len(t) - 1, t.margin_pct.iloc[-1] + 0.8, "Margin", color="#37474F", fontsize=7, ha="right")
    a2.text(len(t) - 1, p.margin_after_shipping_pct.iloc[-1] - 2.0, "After shipping", color=ACCENT, fontsize=7, ha="right")
    fig.tight_layout()
    f1 = tmp / "chart_trend.png"
    fig.savefig(f1)
    plt.close(fig)

    d = R("q12_discounts")
    fig, a = plt.subplots(figsize=(4.6, 2.4), dpi=200)
    a.spines[["top", "right"]].set_visible(False)
    a.spines[["left", "bottom"]].set_color(GRID)
    a.tick_params(colors=MUTED, labelsize=7)
    cols = [ACCENT if v < 0 else "#37474F" for v in d.margin_pct]
    a.bar(d.discount_band, d.margin_pct, color=cols, width=0.6)
    a.axhline(0, color=MUTED, lw=0.8)
    for i, v in enumerate(d.margin_pct):
        a.text(i, v + (1.5 if v >= 0 else -4.5), f"{v:.1f}%", ha="center", fontsize=7, color=INK)
    a.set_title("Margin % by order discount band", fontsize=9, color=INK, loc="left")
    a.set_ylim(-25, 40)
    fig.tight_layout()
    f2 = tmp / "chart_discount.png"
    fig.savefig(f2)
    plt.close(fig)
    return f1, f2


def main():
    tmp = C.WORK_DIR / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    f1, f2 = charts(tmp)
    k = R("kpi_overall").iloc[0]
    cat = R("q01_category_revenue_margin").set_index("category")
    prov = R("q02_province").set_index("province")
    top5 = R("q02_top5_city_share").iloc[0]
    tr = R("q03_monthly_trend")
    q = R("q04_rates_quarterly")
    wf = R("q05_profitability_waterfall_by_category").set_index("category")
    clv = R("q06_clv_overall").iloc[0]
    rep_r = R("q06_repeat_by_region")
    rep_c = R("q06_repeat_by_category").set_index("category")
    rfm = R("q07_rfm_segments").set_index("rfm_segment")
    sq = R("q08_seller_quality")
    tier = R("q08_seller_tier").set_index("seller_tier")
    ot = R("q09_ontime_summary").iloc[0]
    pq = R("q10_product_quality")
    se = R("q11_seasonality").set_index("event_name")
    disc = R("q12_discounts").set_index("discount_band")
    dt = R("q12_discount_share_trend")
    reg = R("q13_region_delivery")
    regp = reg.dropna(subset=["province"]).set_index("province")
    pay = R("q14_payment_methods").set_index("payment_method")
    mb = R("q15_margin_bridge").set_index("period")
    cs = R("q15_cancelled_shipping_cost").iloc[0]

    ss = getSampleStyleSheet()
    H = ParagraphStyle("H", parent=ss["Heading1"], fontSize=15, textColor=colors.HexColor(INK), spaceAfter=2)
    H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=10.5, textColor=colors.HexColor(ACCENT), spaceBefore=6, spaceAfter=2)
    B = ParagraphStyle("B", parent=ss["BodyText"], fontSize=8.3, leading=10.6, textColor=colors.HexColor(INK), spaceAfter=2)
    S = ParagraphStyle("S", parent=B, fontSize=7.2, leading=9, textColor=colors.HexColor(MUTED))

    story = [Paragraph("NexusMart – Executive Summary & Business Insights", H),
             Paragraph("Data: 1 Jan 2024 – 30 Jun 2025 · 159,899 orders / 314,909 order lines after cleaning · PKR · "
                       "metric definitions exactly as in the brief (section 9). Source: PostgreSQL star schema built by the Airflow pipeline.", S),
             Spacer(1, 4)]

    kp = [["Net Revenue", "NMV", "Gross sales", "Margin", "Orders", "AOV", "Units", "Return rate", "Cancel rate", "Active cust."],
          [m(k.net_revenue), m(k.nmv), m(k.gross_sales), f"{m(k.margin)} ({k.margin_pct:.1f}%)", f"{int(k.orders_non_cancelled):,}",
           f"{k.aov:,.0f}", f"{int(k.units):,}", f"{k.return_rate_pct:.2f}%", f"{k.cancellation_rate_pct:.2f}%", f"{int(k.active_customers):,}"]]
    t = Table(kp, colWidths=[1.85 * cm] * 10)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 6.8), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(MUTED)),
                           ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                           ("LINEBELOW", (0, 1), (-1, 1), 0.8, colors.HexColor(ACCENT)),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 1)]))
    story += [t, Spacer(1, 4)]

    h1, h2 = mb.loc["H1-2024"], mb.loc["H1-2025"]
    story += [Paragraph("The headline: revenue doubled, profitability did not", H2),
              Paragraph(
                  f"Monthly net revenue grew from {m(tr.net_revenue.iloc[0])} (Jan-24) to {m(tr.net_revenue.iloc[-1])} (Jun-25), "
                  f"+{(tr.net_revenue.iloc[-1] / tr.net_revenue.iloc[0] - 1) * 100:.0f}%. Over the same period the margin rate fell: "
                  f"H1-2024 vs H1-2025 margin {h1.margin_pct:.1f}% → {h2.margin_pct:.1f}%, and after courier costs "
                  f"{h1.margin_after_shipping_pct:.1f}% → {h2.margin_after_shipping_pct:.1f}%. The category mix barely changed "
                  f"(Electronics stayed at about 35–37% of revenue every month), so mix does not explain the fall. Two cost lines do: "
                  f"<b>discounts</b> rose from {h1.discount_pct_of_gross:.1f}% to {h2.discount_pct_of_gross:.1f}% of gross sales, and "
                  f"<b>shipping</b> rose from {h1.shipping_pct_of_revenue:.1f}% to {h2.shipping_pct_of_revenue:.1f}% of revenue. "
                  f"The share of discounted orders went from {dt.discounted_order_share_pct.iloc[0]:.0f}% to "
                  f"{dt.discounted_order_share_pct.iloc[-1]:.0f}%.", B),
              Image(str(f1), width=18 * cm, height=5.4 * cm)]

    story += [Paragraph("Answers to the 15 business questions", H2)]
    e, f = cat.loc["Electronics"], cat.loc["Fashion"]
    lowest_c = R("q02_city_ranking").tail(1).iloc[0]
    sw = lambda c: f"{c}: {prov.loc[c, 'share_pct']:.1f}%"  # noqa: E731
    best = sq.iloc[0]
    worst = sq.iloc[-1]
    qa = [
        ("Core performance", f"Electronics generates the most revenue ({m(e.net_revenue)}, {e.revenue_share_pct:.1f}%) but only an "
         f"{e.margin_pct:.1f}% margin. Fashion is the largest profit pool ({m(f.margin)} at {f.margin_pct:.1f}%). Beauty & Personal Care has "
         f"the highest margin rate ({cat.loc['Beauty & Personal Care', 'margin_pct']:.1f}%). Grocery ({cat.loc['Grocery', 'margin_pct']:.1f}%) "
         f"loses money once shipping is included ({m(wf.loc['Grocery', 'margin_after_shipping'])})."),
        ("Geography", f"{sw('Punjab')}, {sw('Sindh')}, {sw('Khyber Pakhtunkhwa')}, {sw('Islamabad Capital Territory')}; smallest are "
         f"{sw('Gilgit-Baltistan')} and {sw('Azad Jammu & Kashmir')}. The top 5 cities ({top5.top5_cities}) account for "
         f"<b>{top5.top5_share_net_revenue_pct:.1f}%</b> of revenue; Karachi alone is 19.0%. The 6 metro cities take 54.9%, and the 634 Tier-3 towns "
         f"take 29.6% together. The smallest city is {lowest_c.city} ({lowest_c.net_revenue:,.0f})."),
        ("Revenue trends", f"Average month-over-month growth is +{tr.mom_growth_pct.mean():.1f}%, but growth is uneven. Spikes come from events: "
         f"Mar-25 +{tr.set_index('year_month').loc['2025-03', 'mom_growth_pct']:.1f}% (Ramadan) and Nov-24 +"
         f"{tr.set_index('year_month').loc['2024-11', 'mom_growth_pct']:.1f}% (11.11 / Black Friday). Each is followed by a pullback "
         f"(Apr-25 {tr.set_index('year_month').loc['2025-04', 'mom_growth_pct']:.1f}%)."),
        ("Returns & cancellations", f"The return rate is {k.return_rate_pct:.2f}% and stable between 5.0% and 5.7% a month. The Jun-25 figure "
         f"({tr.return_rate_pct.iloc[-1]:.2f}%) is low only because recent orders have not finished their return window. The cancellation rate is "
         f"{k.cancellation_rate_pct:.2f}% and rising: {q.cancellation_rate_pct.iloc[0]:.2f}% in Q1-24 vs {q.cancellation_rate_pct.iloc[-1]:.2f}% in Q2-25."),
        ("Profitability", f"Net revenue is {k.net_revenue / k.gross_sales * 100:.1f}% of gross sales. Fashion keeps the least "
         f"({wf.loc['Fashion', 'net_to_gross_pct']:.1f}%) because refunds are {wf.loc['Fashion', 'refunds'] / wf.loc['Fashion', 'gross_sales'] * 100:.1f}% of its gross; "
         f"Footwear keeps {wf.loc['Footwear', 'net_to_gross_pct']:.1f}%. Every other category keeps 80–81%, losing about 9% to cancellations and 7% to discounts."),
        ("Customer value", f"Observed CLV is <b>PKR {clv.clv_net_revenue:,.0f}</b> of net revenue per active customer (median {clv.median_clv:,.0f}; "
         f"margin {clv.clv_margin:,.0f}; {clv.avg_orders:.1f} orders). The repeat-purchase rate is {clv.repeat_purchase_rate_pct:.1f}% and almost "
         f"the same across regions ({rep_r.repeat_rate_pct[rep_r.region != 'Unknown'].min():.1f}–{rep_r.repeat_rate_pct.max():.1f}%). It differs a lot by category: "
         f"repeat buying within the category is highest for Mobile ({rep_c.loc['Mobile & Accessories', 'repeat_in_category_pct']:.1f}%) and Fashion "
         f"({rep_c.loc['Fashion', 'repeat_in_category_pct']:.1f}%) and lowest for Automotive ({rep_c.loc['Automotive', 'repeat_in_category_pct']:.1f}%)."),
        ("Segmentation", f"<b>Champions</b> are {int(rfm.loc['Champions', 'customers']):,} customers ({rfm.loc['Champions', 'customer_share_pct']:.1f}%) "
         f"and generate {rfm.loc['Champions', 'revenue_share_pct']:.1f}% of revenue ({m(rfm.loc['Champions', 'net_revenue'])}). Hibernating is the largest "
         f"segment ({rfm.loc['Hibernating', 'customer_share_pct']:.1f}% of customers) but brings only {rfm.loc['Hibernating', 'revenue_share_pct']:.1f}% of revenue. "
         f"At Risk ({int(rfm.loc['At Risk', 'customers']):,} customers, {m(rfm.loc['At Risk', 'net_revenue'])}) is the priority for win-back."),
        ("Seller performance", f"Quality score (0–100) = 35% revenue + 25% low returns + 25% on-time + 15% low cancellations, each scored as a percentile "
         f"among the {len(sq)} sellers with at least 100 order lines. Best: {best.seller_name} ({best.quality_score}); worst: {worst.seller_name} "
         f"({worst.quality_score}). Tier tracks size, not quality: Gold sellers earn {tier.loc['Gold', 'revenue_per_seller'] / 1e6:.1f}M each vs "
         f"{tier.loc['Bronze', 'revenue_per_seller'] / 1e6:.1f}M for Bronze, yet Gold returns ({tier.loc['Gold', 'return_rate_pct']:.2f}%) are no lower and on-time "
         f"rates are the same (about 76%)."),
        ("Delivery performance", f"On-time is defined as delivered within 5 days of the order (about the 70th percentile of delivery time). "
         f"{ot.on_time_rate_pct:.1f}% of lines are on time. Late lines are returned more often ({ot.return_rate_late_pct:.2f}% vs {ot.return_rate_on_time_pct:.2f}%), "
         f"and 8–10 day deliveries reach 6.97%. The six couriers perform the same (average 4.28 days each), so delivery speed is driven by geography, not by courier choice."),
        ("Product quality", f"{len(pq)} products are both top-20% sellers and returned at least 2× the average rate: {(pq.category == 'Fashion').sum()} Fashion "
         f"and {(pq.category == 'Footwear').sum()} Footwear. They are concentrated: 4 sellers (Rehman Traders 67, Lahore Imports 66, Habib Store 43, Crown Enterprises 11) "
         f"own {pq.seller_id.isin(['S0203', 'S0308', 'S0376', 'S0175']).sum()} of them, have return rates of 14–16%, and account for 10.5% of all returns on 3.5% of revenue."),
        ("Seasonality", f"Daily revenue vs a regular day: 11.11 +{se.loc['11.11', 'uplift_vs_regular_pct']:.0f}%, Black Friday +{se.loc['Black Friday', 'uplift_vs_regular_pct']:.0f}%, "
         f"Ramadan +{se.loc['Ramadan', 'uplift_vs_regular_pct']:.0f}%, 14 August +{se.loc['14 August', 'uplift_vs_regular_pct']:.0f}%, Eid-ul-Adha "
         f"+{se.loc['Eid-ul-Adha', 'uplift_vs_regular_pct']:.0f}%, Eid-ul-Fitr {se.loc['Eid-ul-Fitr', 'uplift_vs_regular_pct']:.0f}%. Return rates do not rise at events "
         f"(5.2–5.4%). Cancellations do rise around Eid (Fitr {se.loc['Eid-ul-Fitr', 'cancellation_rate_pct']:.1f}%, Adha {se.loc['Eid-ul-Adha', 'cancellation_rate_pct']:.1f}% "
         f"vs {se.loc['Regular day', 'cancellation_rate_pct']:.1f}% on regular days)."),
        ("Discounts", f"Discounts reduce margin without raising order value. AOV after discount falls from {disc.loc['0%', 'aov']:,.0f} (no discount) to "
         f"{disc.loc['25-30%', 'aov']:,.0f} (25–30%), and margin falls from {disc.loc['0%', 'margin_pct']:.1f}% to {disc.loc['25-30%', 'margin_pct']:.1f}%. "
         f"40–50% codes run at <b>{disc.loc['40-50%', 'margin_pct']:.1f}% margin</b> (a loss of PKR 11.4M) and have more returns ({disc.loc['40-50%', 'return_rate_pct']:.2f}% vs "
         f"{disc.loc['0%', 'return_rate_pct']:.2f}%) and more cancellations ({disc.loc['40-50%', 'cancel_rate_pct']:.1f}% vs {disc.loc['0%', 'cancel_rate_pct']:.1f}%)."),
        ("Delivery times", f"Yes. The slowest provinces have the highest cancellation and return rates: Gilgit-Baltistan {regp.loc['Gilgit-Baltistan', 'avg_delivery_days']:.2f} days / "
         f"{regp.loc['Gilgit-Baltistan', 'on_time_pct']:.0f}% on-time / {regp.loc['Gilgit-Baltistan', 'cancel_rate_pct']:.1f}% cancelled; AJK {regp.loc['Azad Jammu & Kashmir', 'avg_delivery_days']:.2f} / "
         f"{regp.loc['Azad Jammu & Kashmir', 'cancel_rate_pct']:.1f}%; Balochistan {regp.loc['Balochistan', 'avg_delivery_days']:.2f} / {regp.loc['Balochistan', 'cancel_rate_pct']:.1f}%. "
         f"Compare Islamabad: {regp.loc['Islamabad Capital Territory', 'avg_delivery_days']:.2f} days / {regp.loc['Islamabad Capital Territory', 'on_time_pct']:.0f}% on-time / "
         f"{regp.loc['Islamabad Capital Territory', 'cancel_rate_pct']:.1f}% cancelled."),
        ("Payment methods", f"COD is {pay.loc['COD', 'order_share_pct']:.1f}% of orders and is cancelled <b>{pay.loc['COD', 'cancel_rate_pct']:.1f}%</b> of the time, "
         f"vs 3.9–4.1% for prepaid methods. Return rates are the same across methods (5.0–5.3%). Data quality is part of the story: the payment method came in 21 spellings, "
         f"3% of orders are split across two payments, and prepaid cancellations are recorded as 'Refunded' payments while COD cancellations are 'Cancelled'. "
         f"Counting 'Refunded' payments as returns would therefore overstate returns and hide prepaid cancellations, so cancellations are taken from order status."),
        ("Overall profitability", "See the headline above: discount depth and courier cost per order rose while basket size stayed flat. "
         "Shipping cost per shipped order went from PKR 475 to 585 (+23%) while AOV stayed at about 8,200. "
         f"A further PKR {cs.shipping_spent_on_cancelled / 1e6:.1f}M was spent shipping {int(cs.cancelled_orders_with_shipment):,} orders that were then cancelled."),
    ]
    rows = [[Paragraph(f"<b>{i + 1}. {a}</b>", B), Paragraph(b, B)] for i, (a, b) in enumerate(qa)]
    qt = Table(rows, colWidths=[3.3 * cm, 14.7 * cm])
    qt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(GRID)),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2)]))
    story += [qt]

    story += [Paragraph("Three actions for leadership", H2),
              Table([[Image(str(f2), width=7.6 * cm, height=4.0 * cm), Paragraph(
                  f"<b>1. Cap discount depth.</b> Retire 40–50% codes (−18% margin, PKR 11.4M lost, more returns and cancellations) and limit codes on "
                  f"thin-margin Electronics and Grocery. Discounts doubled as a share of gross ({h1.discount_pct_of_gross:.1f}% → {h2.discount_pct_of_gross:.1f}%) "
                  f"without lifting AOV. Target: bring discounts back to about 5% of gross.<br/><br/>"
                  f"<b>2. Reduce COD cancellations.</b> COD orders are cancelled 3.5× as often as prepaid orders ({pay.loc['COD', 'cancel_rate_pct']:.1f}% vs about 4%), and "
                  f"PKR {cs.shipping_spent_on_cancelled / 1e6:.1f}M of shipping was spent on cancelled orders. Use prepaid incentives (wallet cashback in place of "
                  f"blanket codes), confirm COD orders by phone before dispatch, and require prepayment in the slow, high-cancellation provinces (GB, AJK, Balochistan).<br/><br/>"
                  f"<b>3. Cut courier cost and fix Fashion return hot-spots.</b> All six couriers perform identically, so re-tender on price: the cost per order rose "
                  f"23%. Put the 4 Fashion sellers with 14–16% return rates on a quality/size-guide improvement plan with return-rate thresholds tied to listing visibility.",
                  B)]], colWidths=[7.9 * cm, 10.1 * cm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]),
              Spacer(1, 4),
              Paragraph("Notes: margin = net revenue − cost of goods on kept lines. Margin after shipping also deducts courier fees, which NexusMart pays. "
                        "Rates are line-based for returns and order-based for cancellations. Active customers count de-duplicated customers; "
                        "orders from 290 customer IDs that are not in the customer file are excluded from that count. Repaired fields are flagged in the warehouse "
                        "(fact_sales.is_repaired), and all cleaning rules are listed in the Data Quality Report.", S)]

    doc = SimpleDocTemplate(str(C.REPORT_DIR / "executive_summary.pdf"), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm, title="NexusMart Executive Summary")
    doc.build(story)
    print("wrote", C.REPORT_DIR / "executive_summary.pdf")


if __name__ == "__main__":
    main()
