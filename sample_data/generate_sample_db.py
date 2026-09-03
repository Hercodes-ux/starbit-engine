"""
Generates sample_data/company.db — a tiny two-table SQLite database
with a deliberate revenue anomaly in April, and a pricing table whose
price hike that same month explains it. This lets you demo Starbit
Engine's full reasoning chain out of the box:

    "I see a drop in revenue in April; let me check the pricing table."

Run with:
    python generate_sample_db.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "company.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

cur.execute("""
CREATE TABLE revenue (
    month TEXT,
    region TEXT,
    units_sold INTEGER,
    revenue REAL
)
""")

cur.execute("""
CREATE TABLE pricing (
    month TEXT,
    region TEXT,
    unit_price REAL
)
""")

months = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"]
regions = ["North America", "Europe", "APAC"]

# Steady growth, EXCEPT April in Europe where a price hike tanked units sold
base_units = {"North America": 1200, "Europe": 900, "APAC": 700}
base_price = {"North America": 42.0, "Europe": 39.0, "APAC": 35.0}

revenue_rows = []
pricing_rows = []

for i, month in enumerate(months):
    for region in regions:
        units = base_units[region] + i * 60
        price = base_price[region]

        if region == "Europe" and month == "2025-04":
            price = base_price[region] * 1.35     # 35% price hike
            units = int(units * 0.55)               # demand collapsed

        revenue = round(units * price, 2)
        revenue_rows.append((month, region, units, revenue))
        pricing_rows.append((month, region, round(price, 2)))

cur.executemany("INSERT INTO revenue VALUES (?, ?, ?, ?)", revenue_rows)
cur.executemany("INSERT INTO pricing VALUES (?, ?, ?)", pricing_rows)

con.commit()
con.close()
print(f"Created {DB_PATH} with tables: revenue, pricing")
