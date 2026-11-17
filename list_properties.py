import sys
from app.database import engine
from sqlalchemy import text

# Ensure UTF-8 output encoding for terminal on Windows
if sys.platform == "win32":
    try:
        if sys.stdout and sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def show_tables():
    with engine.connect() as conn:
        print("=" * 80)
        print("🏠 1. PRICED PROPERTY LISTINGS (from 'properties' table)")
        print("=" * 80)
        res = conn.execute(text("SELECT id, title, property_type, city, area, monthly_rent, bedrooms FROM properties ORDER BY id ASC"))
        rows = list(res)
        if not rows:
            print("No records found.")
        else:
            for r in rows:
                bhk = f" | {r.bedrooms} BHK" if r.bedrooms else ""
                print(f"[{r.id}] {r.title} ({r.property_type}) - {r.area}, {r.city} | ₹{int(r.monthly_rent):,}/month{bhk}")

        print("\n" + "=" * 80)
        print("📍 2. REAL ACCOMMODATION PLACES (from 'property_places' table - First 15)")
        print("=" * 80)
        res2 = conn.execute(text("SELECT id, name, property_type, area, city, phone FROM property_places ORDER BY id ASC LIMIT 15"))
        for r in res2:
            phone_str = f" | Phone: {r.phone}" if r.phone else ""
            print(f"[{r.id}] {r.name} ({r.property_type}) - {r.area}, {r.city}{phone_str}")

        print("\n" + "=" * 80)
        print("📊 3. TOTAL ACCOMMODATIONS BY TYPE & CITY")
        print("=" * 80)
        res3 = conn.execute(text("SELECT city, property_type, count(*) as cnt FROM property_places GROUP BY city, property_type ORDER BY city, property_type"))
        for r in res3:
            print(f"  • {r.city:<12} | {r.property_type:<10} : {r.cnt} places")
        print("=" * 80)

if __name__ == "__main__":
    show_tables()

