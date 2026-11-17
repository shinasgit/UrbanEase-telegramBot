"""
Public Property Places Data Collector for UrbanEase
==================================================
This module collects real-world public accommodation places (Hostels, PGs,
Flats / Apartments, and Guest Houses) for Bangalore and Kochi using the
OpenStreetMap Overpass API and stores them in the dedicated 'property_places'
PostgreSQL table.

Key Principles:
- Ethical & Legal Compliance: Uses only free, open public data from OpenStreetMap.
  No scraping of gated real-estate portals or paywalled listings.
- No Fabricated Data: Does NOT invent fake rents, fake inventory, or imaginary unit numbers.
  Places are stored as verified real-world physical accommodations.
- Transparent Classification: Deterministic rules mapping OSM tags to
  'Hostel', 'PG', 'Flat', or 'House'.
- Deduplication: Uses OSM element ID (e.g. 'node/12345') to prevent duplicate records.
- Batch / Offline Only: Never called during Telegram bot user requests.
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
    ensure_property_places_schema,
    upsert_property_place,
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
# Rule-Based Property Classification
# ---------------------------------------------------------------------------
def classify_property_type(tags: dict) -> str:
    """
    Transparent rule-based classifier that categorizes an OSM accommodation place into:
      - 'Hostel' (youth hostels, backpacker hostels, working men/women hostels)
      - 'PG' (paying guest, student accommodation, co-living)
      - 'Flat' (apartments, residential complexes, towers)
      - 'House' (guest houses, homestays, villas, individual residences)
    """
    amenity = (tags.get("amenity") or "").lower().strip()
    tourism = (tags.get("tourism") or "").lower().strip()
    building = (tags.get("building") or "").lower().strip()
    name = (tags.get("name") or tags.get("name:en") or "").lower().strip()
    desc = (tags.get("description") or "").lower().strip()

    combined = f"{amenity} {tourism} {building} {name} {desc}"

    # 1. Check for PG / Student Accommodation / Co-living
    if (
        amenity == "student_accommodation"
        or "paying guest" in combined
        or " colive" in combined
        or "co-living" in combined
        or "pg for" in name
        or "ladies pg" in name
        or "gents pg" in name
        or "luxury pg" in name
        or name.endswith(" pg")
        or "zolo " in name
        or "stanza living" in name
    ):
        return "PG"

    # 2. Check for Hostel
    if (
        amenity == "hostel"
        or tourism == "hostel"
        or "hostel" in combined
        or "backpacker" in combined
        or "zostel" in name
    ):
        return "Hostel"

    # 3. Check for Flat / Apartment
    if (
        building == "apartments"
        or building == "residential"
        or "apartment" in combined
        or "heights" in combined
        or "residency" in combined
        or "towers" in combined
        or "enclave" in combined
        or "flats" in combined
    ):
        return "Flat"

    # 4. Check for House / Guest House / Villa / Homestay
    if (
        tourism == "guest_house"
        or "guest house" in combined
        or "guesthouse" in combined
        or "homestay" in combined
        or "villa" in combined
        or "bungalow" in combined
        or "cottage" in combined
    ):
        return "House"

    # Default fallback
    return "Flat"


# ---------------------------------------------------------------------------
# Overpass Query Execution & Extraction
# ---------------------------------------------------------------------------
def build_overpass_query(bbox: str) -> str:
    """
    Constructs an Overpass QL query for verified accommodation places.
    Uses exact tag matches to maintain sub-minute query latency.
    """
    return f"""
    [out:json][timeout:50];
    (
      node["tourism"="hostel"]{bbox};
      way["tourism"="hostel"]{bbox};
      node["amenity"="hostel"]{bbox};
      way["amenity"="hostel"]{bbox};
      node["tourism"="guest_house"]{bbox};
      way["tourism"="guest_house"]{bbox};
      node["amenity"="student_accommodation"]{bbox};
      way["amenity"="student_accommodation"]{bbox};
      node["building"="apartments"]["name"]{bbox};
      way["building"="apartments"]["name"]{bbox};
    );
    out center tags;
    """


def fetch_osm_property_places(bbox: str, label: str) -> list[dict]:
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


def extract_place_record(element: dict, city: str) -> dict | None:
    """
    Extracts and normalizes property place data from an OSM element.
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
        or tags.get("addr:place")
    )
    if area:
        area = area.strip()

    # Extract address
    addr_parts = []
    if tags.get("addr:housenumber"):
        addr_parts.append(f"#{tags['addr:housenumber']}")
    if tags.get("addr:street"):
        addr_parts.append(tags["addr:street"])
    if area and area not in addr_parts:
        addr_parts.append(area)
    if tags.get("addr:postcode"):
        addr_parts.append(tags["addr:postcode"])

    address = ", ".join(addr_parts) if addr_parts else tags.get("addr:full")

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

    # Classify property type
    property_type = classify_property_type(tags)

    # Build description
    desc_parts = []
    if tags.get("description"):
        desc_parts.append(tags["description"].strip())
    if tags.get("rooms"):
        desc_parts.append(f"Rooms: {tags['rooms']}")
    if tags.get("beds"):
        desc_parts.append(f"Beds: {tags['beds']}")
    if tags.get("internet_access") in ["yes", "wlan", "wifi"]:
        desc_parts.append("WiFi Available")

    description = " | ".join(desc_parts) if desc_parts else None

    return {
        "name": name,
        "property_type": property_type,
        "city": city,
        "area": area or city,
        "address": address,
        "phone": phone,
        "website": website,
        "latitude": lat,
        "longitude": lon,
        "source": "OpenStreetMap",
        "source_id": source_id,
        "description": description,
    }


# ---------------------------------------------------------------------------
# Main Collection Flow
# ---------------------------------------------------------------------------
def collect_and_store_property_places() -> dict:
    """
    Main orchestration function:
      1. Ensures database schema exists.
      2. Iterates over target regions.
      3. Fetches OSM elements and deduplicates.
      4. Upserts records into 'property_places'.
      5. Returns detailed collection summary.
    """
    print("=" * 70)
    print("🏠 UrbanEase Real Property Places Collector (OpenStreetMap)")
    print("=" * 70)

    # 1. Ensure database schema
    print("\n1. Initializing database schema...")
    if not ensure_property_places_schema():
        print("❌ Could not verify database schema. Exiting.")
        return {"error": "Database schema verification failed"}
    print("✅ Table 'property_places' and unique index ready.")

    total_fetched = 0
    total_inserted = 0
    total_updated = 0
    total_skipped = 0
    type_counts = {"Hostel": 0, "PG": 0, "Flat": 0, "House": 0}
    city_counts = {"Bangalore": 0, "Kochi": 0}

    seen_source_ids = set()

    # 2. Query each region
    print("\n2. Fetching real accommodation places from OpenStreetMap...")
    for region in CITY_REGIONS:
        city = region["city"]
        label = region["label"]
        bbox = region["bbox"]

        elements = fetch_osm_property_places(bbox, label)
        total_fetched += len(elements)

        for el in elements:
            rec = extract_place_record(el, city)
            if not rec:
                continue

            sid = rec["source_id"]
            if sid in seen_source_ids:
                continue
            seen_source_ids.add(sid)

            status, _ = upsert_property_place(rec)
            if status == "inserted":
                total_inserted += 1
            elif status == "updated":
                total_updated += 1
            else:
                total_skipped += 1

            ptype = rec["property_type"]
            type_counts[ptype] = type_counts.get(ptype, 0) + 1
            city_counts[city] = city_counts.get(city, 0) + 1

        # Respectful pause between regions
        time.sleep(2)

    # 3. Summary Report
    print("\n" + "=" * 70)
    print("📊 Property Places Ingestion Summary")
    print("=" * 70)
    print(f"Total OSM Elements Queried: {total_fetched}")
    print(f"Unique Valid Places:        {len(seen_source_ids)}")
    print(f"  - Newly Inserted:         {total_inserted}")
    print(f"  - Updated (Existing):     {total_updated}")
    print(f"  - Skipped / Errors:       {total_skipped}")
    print("\nDistribution by Property Type:")
    for pt, count in sorted(type_counts.items()):
        print(f"  • {pt:<10}: {count}")
    print("\nDistribution by City:")
    for c, count in sorted(city_counts.items()):
        print(f"  • {c:<10}: {count}")
    print("=" * 70)

    return {
        "total_queried": total_fetched,
        "unique_valid": len(seen_source_ids),
        "inserted": total_inserted,
        "updated": total_updated,
        "skipped": total_skipped,
        "by_type": type_counts,
        "by_city": city_counts,
    }


if __name__ == "__main__":
    collect_and_store_property_places()

