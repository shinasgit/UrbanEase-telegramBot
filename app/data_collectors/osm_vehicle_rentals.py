"""
OpenStreetMap (OSM) Vehicle Rental Data Collector for UrbanEase
==============================================================
This module collects real-world vehicle rental businesses (Bike, Car, and Both)
for Bangalore and Kochi using the OpenStreetMap Overpass API and stores them
in the dedicated 'vehicle_rental_providers' PostgreSQL table.

Key Principles:
- Offline / Batch Ingestion: Never called during user Telegram searches.
- No Fake Data: Stores genuine rental businesses without fabricating individual vehicle models or rates.
- Rule-Based Classification: Transparent mapping to 'Bike', 'Car', or 'Both'.
- Deduplication: Uses OSM element ID (e.g. 'node/12345') to prevent duplicate records.
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
    ensure_vehicle_rental_providers_schema,
    upsert_vehicle_rental_provider,
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

# Custom User-Agent clearly identifying the project
USER_AGENT = "UrbanEase-Assistant-Bot/1.0 (vehicle rental collector; educational project; github.com/shinasgit/UrbanEase-telegramBot)"

# Target cities and geographic query regions: (south_lat, west_lon, north_lat, east_lon)
# Bangalore is split into two regions for query performance, but records are stored with city="Bangalore".
CITY_REGIONS = [
    {"city": "Bangalore", "label": "Bangalore (South)", "bbox": "(12.83,77.45,12.98,77.62)"},
    {"city": "Bangalore", "label": "Bangalore (North)", "bbox": "(12.98,77.56,13.14,77.78)"},
    {"city": "Kochi", "label": "Kochi", "bbox": "(9.85,76.15,10.15,76.45)"},
]


# ---------------------------------------------------------------------------
# Rule-Based Vehicle Rental Classification
# ---------------------------------------------------------------------------
def classify_vehicle_rental_type(tags: dict) -> str:
    """
    Transparent rule-based classifier that categorizes an OSM rental provider into:
      - 'Bike' (motorcycles, scooters, two-wheelers)
      - 'Car' (cars, cabs, self-drive four-wheelers)
      - 'Both' (services offering both or generic vehicle rentals)
    """
    amenity = (tags.get("amenity") or "").lower().strip()
    shop = (tags.get("shop") or "").lower().strip()
    office = (tags.get("office") or "").lower().strip()
    name = (tags.get("name") or tags.get("name:en") or "").lower().strip()
    desc = (tags.get("description") or "").lower().strip()

    combined = f"{amenity} {shop} {office} {name} {desc}"

    # Check for Bike / Motorcycle indicators
    is_bike = (
        "motorcycle_rental" in combined
        or "bike_rental" in combined
        or any(k in name for k in [
            "rent a bike", "bike rental", "motorcycle rental", "scooter rental",
            "two wheeler", "byke", "beepkart", "royal brothers"
        ])
    )

    # Check for Car / Cab / Self-Drive indicators
    is_car = (
        "car_rental" in combined
        or any(k in name for k in [
            "rent a car", "car rental", "car hire", "self drive", "cabs",
            "zoomcar", "zoom car", "indus go", "evm wheels", "avis", "hertz",
            "travels", "taxi"
        ])
    )

    if is_bike and is_car:
        return "Both"
    elif is_bike:
        return "Bike"
    elif is_car:
        return "Car"

    # Generic vehicle rental or fallback
    if "vehicle" in combined:
        return "Both"
    return "Car"


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
        cleaned = phone.split(";")[0].strip()
        return cleaned[:100]
    return None


def extract_website(tags: dict) -> str | None:
    """Extracts website URL from OSM tags."""
    website = tags.get("website") or tags.get("contact:website") or tags.get("url")
    return website.strip() if website else None


def parse_osm_vehicle_rental(element: dict, city: str) -> dict | None:
    """
    Parses a raw OpenStreetMap element into a normalized dictionary ready for
    insertion/upsert into the 'vehicle_rental_providers' table.

    Returns:
        dict: Normalized vehicle rental provider record, or None if skipped.
    """
    tags = element.get("tags", {})
    if not isinstance(tags, dict):
        return None

    # Step 4 requirement: Skip if no business name
    name = (tags.get("name") or tags.get("name:en") or "").strip()
    if not name:
        return None

    # Classify vehicle type into 'Bike', 'Car', or 'Both'
    vehicle_type = classify_vehicle_rental_type(tags)

    el_type = element.get("type", "node")
    el_id = element.get("id")
    source_id = f"{el_type}/{el_id}"

    lat, lon = extract_coordinates(element)
    area = extract_area(tags)
    phone = extract_phone(tags)
    website = extract_website(tags)

    raw_desc = tags.get("description")
    if raw_desc and raw_desc.strip():
        description = raw_desc.strip()
    else:
        desc_area = f" in {area}" if area else ""
        type_desc = "bike & car" if vehicle_type == "Both" else vehicle_type.lower()
        description = f"Local {type_desc} rental service{desc_area}, {city} (via OpenStreetMap)."

    return {
        "name": name[:255],
        "vehicle_type": vehicle_type,
        "city": city,
        "area": area[:100] if area else None,
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
# Overpass API Execution
# ---------------------------------------------------------------------------
def query_overpass(query: str) -> list[dict] | None:
    """
    Sends an Overpass QL query using requests with endpoint failover
    and graceful HTTP 429 rate-limiting detection.
    """
    endpoints = [OVERPASS_URL] + OVERPASS_FALLBACK_URLS
    headers = {"User-Agent": USER_AGENT}

    for endpoint in endpoints:
        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=headers,
                timeout=60,
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
                print(f"⚠️ HTTP {response.status_code} from {endpoint}. Trying fallback...", file=sys.stderr)

        except requests.exceptions.Timeout:
            print(f"⏱️ Connection to {endpoint} timed out. Trying fallback...", file=sys.stderr)
        except requests.exceptions.ConnectionError as exc:
            print(f"🔌 Connection error to {endpoint}: {exc}. Trying fallback...", file=sys.stderr)
        except Exception as exc:
            print(f"❌ Unexpected error querying {endpoint}: {exc}", file=sys.stderr)

    return None


def collect_rentals_for_region(city: str, bbox: str, limit: int = 35) -> tuple[dict, list[dict]]:
    """
    Queries Overpass for vehicle rentals in a specific bounding box and upserts results.
    """
    query = f"""
    [out:json][timeout:50];
    (
      node["amenity"="car_rental"]{bbox};
      node["amenity"="motorcycle_rental"]{bbox};
      node["shop"="car_rental"]{bbox};
      node["shop"="motorcycle_rental"]{bbox};
      node["office"="car_rental"]{bbox};
      way["amenity"="car_rental"]{bbox};
      way["amenity"="motorcycle_rental"]{bbox};
    );
    out center {limit};
    """

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
        return stats, sample_records

    stats["found"] = len(elements)

    for el in elements:
        record = parse_osm_vehicle_rental(el, city)
        if not record:
            stats["skipped"] += 1
            continue

        status, rec_id = upsert_vehicle_rental_provider(record)
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
def run_vehicle_rental_collector(limit_per_query: int = 35) -> None:
    """
    Runs the full OpenStreetMap vehicle rental data collection pipeline:
      1. Ensures the 'vehicle_rental_providers' table and unique index exist.
      2. Sequentially queries Overpass API for Bangalore and Kochi.
      3. Classifies businesses into Bike/Car/Both and upserts into PostgreSQL.
      4. Prints a formatted summary and sample records.
    """
    print("=" * 65)
    print("🚗 UrbanEase Vehicle Rental Data Collection")
    print("=" * 65)

    # Step 1: Ensure database schema is ready
    print("🔧 Checking PostgreSQL 'vehicle_rental_providers' schema...")
    if not ensure_vehicle_rental_providers_schema():
        print("❌ Could not verify/update database schema. Aborting.", file=sys.stderr)
        return
    print("✅ Database schema is up-to-date and ready.\n")

    overall_results: dict[str, dict] = {}
    sample_records_by_city: dict[str, list] = {}

    for i, region in enumerate(CITY_REGIONS):
        city = region["city"]
        label = region["label"]
        bbox = region["bbox"]

        # Polite delay between sequential queries
        if i > 0:
            time.sleep(3)

        print(f"📡 Querying OpenStreetMap for {label} (normalized to city: '{city}', limit: {limit_per_query})...")
        stats, samples = collect_rentals_for_region(city, bbox, limit=limit_per_query)

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
            web_str = s.get("website") or "N/A"
            coords = f"({s.get('latitude')}, {s.get('longitude')})" if s.get("latitude") else "N/A"
            print(f"   {idx}. {s.get('name')} | Type: {s.get('vehicle_type')} | Area: {area_str} | Phone: {phone_str}")
            print(f"      Website: {web_str} | OSM ID: {s.get('source_id')} | Coords: {coords}")

    print("\n" + "=" * 65)
    print("✅ Vehicle rental data collection finished successfully!")
    print("=" * 65)


if __name__ == "__main__":
    run_vehicle_rental_collector()

