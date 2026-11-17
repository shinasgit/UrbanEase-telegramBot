"""
OpenStreetMap (OSM) Rental Appliances & Furniture Data Collector for UrbanEase
=============================================================================
This module collects real-world appliance and furniture rental businesses
for Bangalore and Kochi using the OpenStreetMap Overpass API and stores them
in the dedicated 'rental_item_providers' PostgreSQL table.

Key Principles:
- Offline / Batch Ingestion: Never called during user Telegram searches.
- No Fake Data: Stores genuine rental businesses without fabricating individual items, prices, or rates.
- Rule-Based Classification: Transparent mapping to 'Appliance', 'Furniture', or 'Both'.
- Deduplication: Uses OSM element ID (e.g. 'node/12345') to prevent duplicate records.
- Respectful API Usage: Custom User-Agent, sequential non-parallel execution, polite delays,
  and fallback endpoints.
"""

import sys
import time
from pathlib import Path
import requests

# Ensure project root is on sys.path for direct script execution
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Ensure UTF-8 output encoding for terminal on Windows
if sys.platform == "win32":
    try:
        if sys.stdout and sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.database import (
    ensure_rental_item_providers_schema,
    upsert_rental_item_provider,
)

# ---------------------------------------------------------------------------
# Configuration & Endpoints
# ---------------------------------------------------------------------------
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

OVERPASS_FALLBACK_URLS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

USER_AGENT = "UrbanEase-Assistant-Bot/1.0"

# Target cities and geographic query regions
CITY_REGIONS = [
    {"city": "Bangalore", "label": "Bangalore (South)", "bbox": "(12.83,77.45,12.98,77.62)"},
    {"city": "Bangalore", "label": "Bangalore (North)", "bbox": "(12.98,77.56,13.14,77.78)"},
    {"city": "Kochi", "label": "Kochi", "bbox": "(9.85,76.15,10.15,76.45)"},
]


# ---------------------------------------------------------------------------
# Rule-Based Category Classification
# ---------------------------------------------------------------------------
def classify_rental_category(tags: dict) -> str:
    """
    Transparent rule-based classifier that categorizes an OSM rental provider into:
      - 'Appliance' (electronics, washing machines, fridges, TVs, laptops, etc.)
      - 'Furniture' (sofas, beds, tables, wardrobes, chairs, etc.)
      - 'Both' (services offering both or generic home rentals like Rentomojo, Furlenco)
    """
    name = (tags.get("name") or tags.get("name:en") or "").lower().strip()
    rental = (tags.get("rental") or "").lower().strip()
    shop = (tags.get("shop") or "").lower().strip()
    desc = (tags.get("description") or "").lower().strip()

    combined = f"{name} {rental} {shop} {desc}"

    # Known multi-category brands
    if any(b in combined for b in ["rentomojo", "furlenco", "rentickle", "cityfurnish", "grabonrent"]):
        return "Both"

    # Appliance indicators
    is_appliance = (
        "appliance" in combined
        or "electronics" in combined
        or "washing machine" in combined
        or "refrigerator" in combined
        or "fridge" in combined
        or "microwave" in combined
        or "television" in combined
        or "tv rental" in combined
        or "laptop rental" in combined
        or "computer rental" in combined
        or "ac rental" in combined
        or "cooler" in combined
        or "audio" in combined
    )

    # Furniture indicators
    is_furniture = (
        "furniture" in combined
        or "sofa" in combined
        or "bed" in combined
        or "table" in combined
        or "chair" in combined
        or "wardrobe" in combined
        or "mattress" in combined
        or "desk" in combined
        or "office furniture" in combined
    )

    if is_appliance and is_furniture:
        return "Both"
    elif is_appliance:
        return "Appliance"
    elif is_furniture:
        return "Furniture"
    else:
        # Default for generic rental shops
        return "Both"


# ---------------------------------------------------------------------------
# Overpass Query Execution & Extraction
# ---------------------------------------------------------------------------
def build_overpass_query(bbox: str) -> str:
    """
    Constructs an Overpass QL query to find furniture & appliance rental providers.
    Uses exact tag matches and bounded searches for fast response times.
    """
    return f"""
    [out:json][timeout:50];
    (
      node["shop"="rental"]{bbox};
      way["shop"="rental"]{bbox};
      node["rental"="furniture"]{bbox};
      node["rental"="appliances"]{bbox};
      node["rental"="appliance"]{bbox};
      node["rental"="electronics"]{bbox};
      node["shop"="furniture"]["rental"="yes"]{bbox};
      node["shop"="electronics"]["rental"="yes"]{bbox};
      way["shop"="furniture"]["rental"="yes"]{bbox};
      node["shop"="furniture"]["name"~"rent|rental|furlenco|rentomojo",i]{bbox};
      node["shop"="electronics"]["name"~"rent|rental",i]{bbox};
    );
    out center tags;
    """


def fetch_osm_rental_providers(bbox: str, label: str) -> list[dict]:
    """
    Sends the Overpass query to the primary endpoint, trying fallbacks if needed.
    """
    query = build_overpass_query(bbox)
    headers = {
        "User-Agent": USER_AGENT,
    }

    endpoints = [OVERPASS_URL] + OVERPASS_FALLBACK_URLS

    for endpoint in endpoints:
        try:
            print(f"   📡 Querying Overpass API for {label} via {endpoint[:32]}... ", end="", flush=True)
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=headers,
                timeout=60,
            )

            if response.status_code == 200:
                data = response.json()
                elements = data.get("elements", [])
                print(f"✅ Received {len(elements)} raw elements.")
                return elements
            elif response.status_code == 429:
                print(f"⚠️ Rate limited (HTTP 429). Waiting 5 seconds before trying next endpoint...")
                time.sleep(5)
            else:
                print(f"⚠️ HTTP {response.status_code}. Trying next endpoint...")

        except requests.exceptions.RequestException as e:
            print(f"⚠️ Network error: {e}. Trying next endpoint...")

    print(f"   ❌ All endpoints failed for {label}.")
    return []


def extract_provider_record(element: dict, city: str) -> dict | None:
    """
    Extracts and normalizes provider data from an OSM element.
    Returns None if the record lacks a valid name.
    """
    tags = element.get("tags", {})
    name = tags.get("name") or tags.get("name:en")
    if not name or not name.strip():
        return None

    name = name.strip()
    source_id = f"{element.get('type', 'node')}/{element.get('id')}"

    # Extract coordinates
    lat = element.get("lat")
    lon = element.get("lon")
    if lat is None and "center" in element:
        lat = element["center"].get("lat")
        lon = element["center"].get("lon")

    # Extract area / neighbourhood
    area = (
        tags.get("addr:suburb")
        or tags.get("addr:neighbourhood")
        or tags.get("addr:district")
        or tags.get("addr:street")
        or tags.get("addr:place")
    )
    if area:
        area = area.strip()

    # Extract contact info
    phone = (
        tags.get("phone")
        or tags.get("contact:phone")
        or tags.get("contact:mobile")
        or tags.get("mobile")
    )
    if phone:
        phone = phone.strip()

    website = tags.get("website") or tags.get("contact:website")
    if website:
        website = website.strip()

    # Classify rental category
    category = classify_rental_category(tags)

    # Build description
    desc_parts = []
    if tags.get("description"):
        desc_parts.append(tags["description"].strip())
    if tags.get("opening_hours"):
        desc_parts.append(f"Hours: {tags['opening_hours']}")
    if tags.get("addr:full"):
        desc_parts.append(f"Address: {tags['addr:full']}")

    description = " | ".join(desc_parts) if desc_parts else None

    return {
        "name": name,
        "category": category,
        "city": city,
        "area": area,
        "phone": phone,
        "website": website,
        "latitude": lat,
        "longitude": lon,
        "source": "OpenStreetMap",
        "source_id": source_id,
        "description": description,
        "available": True,
    }


# ---------------------------------------------------------------------------
# Main Collection Flow
# ---------------------------------------------------------------------------
def collect_and_store_rental_item_providers() -> dict:
    """
    Main orchestration function:
      1. Ensures database schema exists.
      2. Iterates over target regions.
      3. Fetches OSM elements and deduplicates.
      4. Upserts records into 'rental_item_providers'.
      5. Returns detailed collection summary.
    """
    print("=" * 70)
    print("🛋️ UrbanEase Real-World Rental Item Providers Collector (OpenStreetMap)")
    print("=" * 70)

    # 1. Ensure database schema
    print("\n1. Initializing database schema...")
    if not ensure_rental_item_providers_schema():
        print("❌ Could not verify database schema. Exiting.")
        return {"error": "Database schema verification failed"}
    print("✅ Table 'rental_item_providers' and unique index ready.")

    total_fetched = 0
    total_inserted = 0
    total_updated = 0
    total_skipped = 0
    category_counts = {"Appliance": 0, "Furniture": 0, "Both": 0}
    city_counts = {"Bangalore": 0, "Kochi": 0}

    seen_source_ids = set()

    # 2. Query each region
    print("\n2. Fetching real rental businesses from OpenStreetMap...")
    for region in CITY_REGIONS:
        city = region["city"]
        label = region["label"]
        bbox = region["bbox"]

        elements = fetch_osm_rental_providers(bbox, label)
        total_fetched += len(elements)

        for el in elements:
            rec = extract_provider_record(el, city)
            if not rec:
                continue

            sid = rec["source_id"]
            if sid in seen_source_ids:
                continue
            seen_source_ids.add(sid)

            status, _ = upsert_rental_item_provider(rec)
            if status == "inserted":
                total_inserted += 1
            elif status == "updated":
                total_updated += 1
            else:
                total_skipped += 1

            cat = rec["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1
            city_counts[city] = city_counts.get(city, 0) + 1

        # Respectful pause between regions
        time.sleep(2)

    # 3. Summary Report
    print("\n" + "=" * 70)
    print("📊 Rental Item Providers Ingestion Summary")
    print("=" * 70)
    print(f"Total OSM Elements Queried: {total_fetched}")
    print(f"Unique Valid Providers:     {len(seen_source_ids)}")
    print(f"  - Newly Inserted:         {total_inserted}")
    print(f"  - Updated (Existing):     {total_updated}")
    print(f"  - Skipped / Errors:       {total_skipped}")
    print("\nDistribution by Category:")
    for cat, count in sorted(category_counts.items()):
        print(f"  • {cat:<12}: {count}")
    print("\nDistribution by City:")
    for c, count in sorted(city_counts.items()):
        print(f"  • {c:<12}: {count}")
    print("=" * 70)

    return {
        "total_queried": total_fetched,
        "unique_valid": len(seen_source_ids),
        "inserted": total_inserted,
        "updated": total_updated,
        "skipped": total_skipped,
        "by_category": category_counts,
        "by_city": city_counts,
    }


if __name__ == "__main__":
    collect_and_store_rental_item_providers()

