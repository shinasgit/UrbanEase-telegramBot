"""
OpenStreetMap (OSM) Helper Data Collector for UrbanEase
======================================================
This module collects real-world local business listings for service providers
(Electricians, Plumbers, Carpenters, AC Repair, Cleaners) across Bangalore and Kochi
using the OpenStreetMap Overpass API.

Key Design Principles:
- Offline / Batch Ingestion: Runs independently; never called during Telegram searches.
- Transparent Classification: Rule-based category mapping without LLM dependencies.
- Deduplication & Upsert: Tracks elements by OSM `source_id` ('node/12345', 'way/6789')
  to update existing records rather than creating duplicates.
- Respectful API Usage: Custom User-Agent, sequential non-parallel execution, polite delays,
  and graceful HTTP 429 rate-limit handling.
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
    ensure_service_providers_schema,
    upsert_service_provider,
)

# ---------------------------------------------------------------------------
# Configuration & Endpoints
# ---------------------------------------------------------------------------
# Primary Overpass API endpoint
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Fallback Overpass endpoints in case primary experiences high load / rate limit
OVERPASS_FALLBACK_URLS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Custom User-Agent clearly identifying the project as requested
USER_AGENT = "UrbanEase-Assistant-Bot/1.0 (local helper collector; educational project; github.com/shinasgit/UrbanEase-telegramBot)"

# Target cities and geographic query regions: (south_lat, west_lon, north_lat, east_lon)
# Bangalore is queried in two sub-regions to prevent Overpass timeouts,
# but all collected records are stored with normalized city = "Bangalore".
CITY_REGIONS = [
    {"city": "Bangalore", "label": "Bangalore (South)", "bbox": "(12.83,77.45,12.98,77.62)"},
    {"city": "Bangalore", "label": "Bangalore (North)", "bbox": "(12.98,77.56,13.14,77.78)"},
    {"city": "Kochi", "label": "Kochi", "bbox": "(9.85,76.15,10.15,76.45)"},
]

# The 5 official UrbanEase service categories
TARGET_SERVICES = [
    "Electrician",
    "Plumber",
    "Carpenter",
    "AC Repair",
    "Cleaner",
]


# ---------------------------------------------------------------------------
# Step 4: Service Type Normalization
# ---------------------------------------------------------------------------
def map_osm_service_type(tags: dict) -> str | None:
    """
    Transparent rule-based classifier that maps OpenStreetMap tags
    and business name keywords to the 5 UrbanEase service categories:
      - Electrician
      - Plumber
      - Carpenter
      - AC Repair
      - Cleaner

    Returns:
        str: Normalized category name, or None if no confident match.
    """
    craft = (tags.get("craft") or "").lower().strip()
    shop = (tags.get("shop") or "").lower().strip()
    service = (tags.get("service") or "").lower().strip()
    amenity = (tags.get("amenity") or "").lower().strip()
    name = (tags.get("name") or tags.get("name:en") or "").lower().strip()
    desc = (tags.get("description") or "").lower().strip()

    combined_text = f"{craft} {shop} {service} {amenity} {name} {desc}"

    # 1. Electrician
    if craft in ["electrician", "electrical"] or shop == "electrical" or service == "electrician":
        return "Electrician"
    if any(k in name for k in ["electrician", "electricals", "electrical service", "electrical works", "wiring"]):
        return "Electrician"

    # 2. Plumber
    if craft in ["plumber", "plumbing"] or shop in ["plumber", "plumbing"] or service == "plumber":
        return "Plumber"
    if any(k in name for k in ["plumber", "plumbing", "sanitary ware", "pipe fitting"]):
        return "Plumber"

    # 3. Carpenter
    if craft in ["carpenter", "carpentry", "joiner", "woodworker"] or shop == "carpenter":
        return "Carpenter"
    if any(k in name for k in ["carpenter", "carpentry", "wood works", "woodworks", "wood craft", "wood design"]):
        return "Carpenter"

    # 4. AC Repair
    if craft in ["hvac", "air_conditioning"] or shop in ["hvac", "air_conditioning"] or "ac_repair" in service:
        return "AC Repair"
    if any(k in combined_text for k in ["ac repair", "ac service", "air condition", "air conditioning", "hvac", "cooling service", "refrigeration"]):
        return "AC Repair"

    # 5. Cleaner
    if craft in ["cleaning", "cleaner"] or service in ["cleaning", "housekeeping"] or amenity == "cleaning":
        return "Cleaner"
    if any(k in name for k in ["cleaning service", "housekeeping", "clean home", "cleaners", "deep cleaning", "facility services"]):
        return "Cleaner"

    return None


# ---------------------------------------------------------------------------
# Tag & Coordinate Extraction Helpers
# ---------------------------------------------------------------------------
def extract_coordinates(element: dict) -> tuple[float | None, float | None]:
    """
    Extracts latitude and longitude from an OSM element.
    - Uses 'lat' and 'lon' directly for nodes.
    - Uses 'center.lat' and 'center.lon' for ways and relations when available.
    """
    el_type = element.get("type")
    if el_type == "node":
        lat = element.get("lat")
        lon = element.get("lon")
        return (float(lat) if lat is not None else None, float(lon) if lon is not None else None)

    # For ways and relations, check 'center'
    center = element.get("center", {})
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        return (float(center["lat"]), float(center["lon"]))

    return (None, None)


def extract_area(tags: dict) -> str | None:
    """Combines suburb, neighbourhood, or street into a clean area string."""
    suburb = tags.get("addr:suburb") or tags.get("addr:neighbourhood")
    street = tags.get("addr:street")
    district = tags.get("addr:district")

    if suburb:
        return suburb.strip()
    if street:
        return street.strip()
    if district:
        return district.strip()
    return None


def extract_phone(tags: dict) -> str | None:
    """Extracts and cleans contact phone number from OSM tags."""
    phone = (
        tags.get("phone")
        or tags.get("contact:phone")
        or tags.get("contact:mobile")
        or tags.get("mobile")
    )
    if phone:
        # Standardize multiple numbers separated by ';' by picking the primary one
        cleaned = phone.split(";")[0].strip()
        return cleaned[:50]  # Respect column limit
    return None


def extract_website(tags: dict) -> str | None:
    """Extracts website URL from OSM tags."""
    website = tags.get("website") or tags.get("contact:website") or tags.get("url")
    return website.strip() if website else None


def parse_osm_element(element: dict, city: str) -> dict | None:
    """
    Parses a raw OpenStreetMap element into a normalized dictionary ready for
    insertion/upsert into the PostgreSQL 'service_providers' table.

    Returns:
        dict: Normalized helper record, or None if skipped (e.g. no name or unmapped type).
    """
    tags = element.get("tags", {})
    if not isinstance(tags, dict):
        return None

    # Step 2 requirement: Skip if no business name
    name = (tags.get("name") or tags.get("name:en") or "").strip()
    if not name:
        return None

    # Step 4 requirement: Normalize to one of the 5 categories
    service_type = map_osm_service_type(tags)
    if not service_type:
        return None

    el_type = element.get("type", "node")
    el_id = element.get("id")
    source_id = f"{el_type}/{el_id}"

    lat, lon = extract_coordinates(element)
    area = extract_area(tags)
    phone = extract_phone(tags)
    website = extract_website(tags)

    # Use existing description or generate a helpful fallback
    raw_desc = tags.get("description")
    if raw_desc and raw_desc.strip():
        description = raw_desc.strip()
    else:
        desc_area = f" in {area}" if area else ""
        description = f"Local {service_type.lower()} service{desc_area}, {city} (via OpenStreetMap)."

    return {
        "name": name[:255],
        "service_type": service_type,
        "city": city,
        "area": area[:100] if area else None,
        "phone": phone,
        "description": description,
        "available": True,
        "source": "OpenStreetMap",
        "source_id": source_id,
        "latitude": lat,
        "longitude": lon,
        "website": website,
    }


# ---------------------------------------------------------------------------
# Step 3: Overpass API Query Execution
# ---------------------------------------------------------------------------
def query_overpass(query: str) -> list[dict] | None:
    """
    Sends an Overpass QL query using the Python requests library.
    Tries the primary endpoint first; falls back to secondary mirrors if needed.
    Handles HTTP 429 rate limiting with an immediate exit and friendly warning.

    Returns:
        list[dict]: List of OSM elements on success, or None on failure.
    """
    endpoints = [OVERPASS_URL] + OVERPASS_FALLBACK_URLS
    headers = {"User-Agent": USER_AGENT}

    for endpoint in endpoints:
        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=headers,
                timeout=65,
            )

            # Check HTTP 429 Too Many Requests
            if response.status_code == 429:
                print(f"⚠️ Overpass API Rate Limit (HTTP 429) hit on {endpoint}.", file=sys.stderr)
                print("Stopping collection gracefully as instructed. Please wait a minute before running again.", file=sys.stderr)
                return None

            if response.status_code == 200:
                data = response.json()
                return data.get("elements", [])
            else:
                print(f"⚠️ HTTP {response.status_code} received from {endpoint}. Trying next endpoint...", file=sys.stderr)

        except requests.exceptions.Timeout:
            print(f"⏱️ Connection to {endpoint} timed out. Trying fallback...", file=sys.stderr)
        except requests.exceptions.ConnectionError as exc:
            print(f"🔌 Connection error to {endpoint}: {exc}. Trying fallback...", file=sys.stderr)
        except Exception as exc:
            print(f"❌ Unexpected error querying {endpoint}: {exc}", file=sys.stderr)

    return None


def collect_helpers_for_city(city: str, bbox: str, limit: int = 35) -> tuple[dict, list[dict]]:
    """
    Collects and upserts service provider listings for a single city.

    Returns:
        tuple: (stats_dict, sample_records_list)
    """
    # Overpass QL query targeting official craft and shop tags with bounding box
    # Uses exact tag lookups for maximum server performance and fast execution
    query = f"""
    [out:json][timeout:60];
    (
      node["craft"="electrician"]{bbox};
      node["craft"="plumber"]{bbox};
      node["craft"="carpenter"]{bbox};
      node["craft"="hvac"]{bbox};
      node["craft"="cleaning"]{bbox};
      node["shop"="electrical"]{bbox};
      node["shop"="plumber"]{bbox};
      node["shop"="plumbing"]{bbox};
      node["shop"="hvac"]{bbox};
      way["craft"="electrician"]{bbox};
      way["craft"="plumber"]{bbox};
      way["craft"="carpenter"]{bbox};
      way["craft"="hvac"]{bbox};
      way["craft"="cleaning"]{bbox};
      way["shop"="electrical"]{bbox};
    );
    out center {limit};
    """

    print(f"\n📡 Querying OpenStreetMap for {city} (limit: {limit})...")
    elements = query_overpass(query)

    stats = {
        "found": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "error": 0,
    }
    sample_records = []

    if elements is None:
        print(f"❌ Failed to retrieve OpenStreetMap data for {city}.")
        return stats, sample_records

    stats["found"] = len(elements)

    for el in elements:
        record = parse_osm_element(el, city)
        if not record:
            stats["skipped"] += 1
            continue

        status, rec_id = upsert_service_provider(record)
        if status == "inserted":
            stats["inserted"] += 1
            if len(sample_records) < 3:
                sample_records.append(record)
        elif status == "updated":
            stats["updated"] += 1
            if len(sample_records) < 3:
                sample_records.append(record)
        elif status == "skipped":
            stats["skipped"] += 1
        elif status == "error":
            stats["error"] += 1

    return stats, sample_records


# ---------------------------------------------------------------------------
# Main Runner & Reporting
# ---------------------------------------------------------------------------
def run_osm_collector(limit_per_city: int = 35) -> None:
    """
    Runs the complete OSM data collection workflow:
      1. Ensures the database schema has the required columns & partial index.
      2. Sequentially queries Overpass API for Bangalore and Kochi.
      3. Normalizes and upserts records into PostgreSQL.
      4. Prints a formatted summary and sample records.
    """
    print("=" * 65)
    print("🏙️ UrbanEase OSM Helper Data Collection")
    print("=" * 65)

    # Step 1: Ensure database schema is ready
    print("🔧 Checking PostgreSQL database schema...")
    if not ensure_service_providers_schema():
        print("❌ Could not verify/update database schema. Aborting.", file=sys.stderr)
        return
    print("✅ Database schema is up-to-date and ready.\n")

    overall_results = {}
    sample_records_by_city = {}

    for i, region in enumerate(CITY_REGIONS):
        city = region["city"]
        label = region["label"]
        bbox = region["bbox"]

        # Polite delay between sequential queries to avoid hammering public Overpass servers
        if i > 0:
            time.sleep(3)

        print(f"\n📡 Querying OpenStreetMap for {label} (city: {city}, limit: {limit_per_city})...")
        stats, samples = collect_helpers_for_city(city, bbox, limit=limit_per_city)

        if city not in overall_results:
            overall_results[city] = {"found": 0, "inserted": 0, "updated": 0, "skipped": 0, "error": 0}
            sample_records_by_city[city] = []

        for k in overall_results[city]:
            overall_results[city][k] += stats.get(k, 0)
        sample_records_by_city[city].extend(samples)

    # Print Summary Report
    print("\n" + "=" * 65)
    print("📊 Collection Summary")
    print("=" * 65)

    for city, stats in overall_results.items():
        print(f"\nCity: {city}")
        print(f"Records found:    {stats['found']}")
        print(f"Records inserted: {stats['inserted']}")
        print(f"Records updated:  {stats['updated']}")
        print(f"Records skipped:  {stats['skipped']}")

    # Print Sample Records for Verification
    print("\n" + "=" * 65)
    print("🔍 Sample Collected Records")
    print("=" * 65)

    for city, samples in sample_records_by_city.items():
        print(f"\n📍 {city} Samples:")
        if not samples:
            print("   (No new records were inserted or updated in this run)")
        for idx, s in enumerate(samples[:3], start=1):
            phone_str = s.get("phone") or "N/A"
            area_str = s.get("area") or "N/A"
            coords = f"({s.get('latitude')}, {s.get('longitude')})" if s.get('latitude') else "N/A"
            print(f"   {idx}. {s.get('name')} | Service: {s.get('service_type')} | Area: {area_str} | Phone: {phone_str}")
            print(f"      OSM ID: {s.get('source_id')} | Coords: {coords}")

    print("\n" + "=" * 65)
    print("✅ OpenStreetMap data collection finished successfully!")
    print("=" * 65)


if __name__ == "__main__":
    run_osm_collector()
