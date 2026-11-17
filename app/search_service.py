import json
import sys
from decimal import Decimal
from pathlib import Path

# Ensure UTF-8 output encoding for terminal on Windows
if sys.platform == "win32":
    try:
        if sys.stdout and sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to sys.path so 'app' package can be imported directly
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.ai_service import understand_request
from app.database import (
    search_properties,
    search_property_places,
    search_rental_items_nl,
    search_rental_item_providers,
    search_vehicles_nl,
    search_vehicle_rental_providers,
    search_service_providers,
)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal objects into float/int for display."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def _execute_intent_search(intent: str, ai_data: dict, area: str | None = None) -> list[dict] | None:
    """
    Executes database search for the given intent and AI parameters,
    filtering by the specified area (or omitting area filter if None).
    """
    city = ai_data.get("city")

    # --- 1. Property Search ---
    if intent == "property_search":
        prop_type = ai_data.get("property_type")
        raw_budget = ai_data.get("max_budget")

        max_budget = None
        if raw_budget is not None:
            try:
                max_budget = float(raw_budget)
            except (ValueError, TypeError):
                max_budget = None

        # 1. Search individual property listings with verified prices
        property_listings = search_properties(
            city=city,
            property_type=prop_type,
            max_budget=max_budget,
            area=area,
        )
        if property_listings is None:
            return None

        # 2. If no strict budget filter is specified, also search real accommodation places
        # (Hostels, PGs, Apartments, Guest Houses from OSM)
        property_places = []
        if max_budget is None:
            places = search_property_places(
                city=city,
                property_type=prop_type,
                area=area,
            )
            if places is not None:
                for p in places:
                    desc_parts = []
                    if p.get("description"):
                        desc_parts.append(p["description"])
                    if p.get("address"):
                        desc_parts.append(f"📍 {p['address']}")
                    if p.get("phone"):
                        desc_parts.append(f"📞 Contact: {p['phone']}")
                    if p.get("website"):
                        desc_parts.append(f"🌐 Website: {p['website']}")

                    property_places.append({
                        "id": p.get("id"),
                        "title": p.get("name"),
                        "property_type": p.get("property_type"),
                        "city": p.get("city"),
                        "area": p.get("area"),
                        "monthly_rent": None,
                        "bedrooms": None,
                        "description": "\n".join(desc_parts),
                        "source": p.get("source", "OpenStreetMap"),
                        "phone": p.get("phone"),
                        "website": p.get("website"),
                        "is_place": True,
                    })

        return property_listings + property_places

    # --- 2. Rental Item Search (Appliances & Furniture) ---
    elif intent == "rental_item_search":
        category = ai_data.get("category")
        item_name = ai_data.get("item_name")

        # 1. Search individual rental item listings (sample items)
        rental_listings = search_rental_items_nl(
            city=city,
            category=category,
            item_keyword=item_name,
            area=area,
        )
        if rental_listings is None:
            return None

        # 2. Search real-world rental businesses (OpenStreetMap)
        item_providers = search_rental_item_providers(
            city=city,
            category=category,
            keyword=item_name,
            area=area,
        )
        formatted_providers = []
        if item_providers is not None:
            for p in item_providers:
                desc_parts = []
                if p.get("description"):
                    desc_parts.append(p["description"])
                if p.get("phone"):
                    desc_parts.append(f"📞 Contact: {p['phone']}")
                if p.get("website"):
                    desc_parts.append(f"🌐 Website: {p['website']}")

                formatted_providers.append({
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "city": p.get("city"),
                    "area": p.get("area"),
                    "monthly_rent": None,
                    "description": "\n".join(desc_parts),
                    "available": True,
                    "source": p.get("source", "OpenStreetMap"),
                    "phone": p.get("phone"),
                    "website": p.get("website"),
                    "is_provider": True,
                })

        return rental_listings + formatted_providers

    # --- 3. Vehicle Search (Bikes & Cars) ---
    elif intent == "vehicle_search":
        vehicle_type = ai_data.get("vehicle_type")

        # 1. Search individual vehicle listings (sample vehicles)
        vehicle_listings = search_vehicles_nl(
            city=city,
            vehicle_type=vehicle_type,
            area=area,
        )
        if vehicle_listings is None:
            return None

        # 2. Search real-world vehicle rental providers (OpenStreetMap)
        rental_providers = search_vehicle_rental_providers(
            city=city,
            vehicle_type=vehicle_type,
            area=area,
        )
        formatted_providers = []
        if rental_providers is not None:
            for p in rental_providers:
                desc_parts = []
                if p.get("description"):
                    desc_parts.append(p["description"])
                if p.get("phone"):
                    desc_parts.append(f"📞 Contact: {p['phone']}")
                if p.get("website"):
                    desc_parts.append(f"🌐 Website: {p['website']}")

                formatted_providers.append({
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "vehicle_type": p.get("vehicle_type"),
                    "brand": "Rental Agency",
                    "city": p.get("city"),
                    "area": p.get("area"),
                    "daily_rent": None,
                    "description": "\n".join(desc_parts),
                    "available": True,
                    "source": p.get("source", "OpenStreetMap"),
                    "phone": p.get("phone"),
                    "website": p.get("website"),
                    "is_provider": True,
                })

        return vehicle_listings + formatted_providers

    # --- 4. Helper Search (Electrician, Plumber, etc.) ---
    elif intent == "helper_search":
        service_type = ai_data.get("service_type")
        return search_service_providers(
            service_type=service_type,
            city=city,
            area=area,
        )

    return []


def search_from_message(user_message: str) -> dict:
    """
    Orchestrates the Natural Language search pipeline:
      1. Calls understand_request(user_message) to extract structured AI intent & entities.
      2. Reads the detected intent, city, and area.
      3. Dispatches to the corresponding safe, parameterized PostgreSQL search function.
         - If an area is specified, searches ONLY that area.
         - If NO results are found in the requested area, does NOT automatically fall back to city-wide.
           Instead returns status="area_not_found" with preserved search_data for user confirmation.
         - If no area is specified, performs a normal city-wide search.
      4. Returns structured search response.

    Args:
        user_message (str): Natural language message from the user.

    Returns:
        dict: {
            "query": str,
            "understanding": dict,
            "results": list[dict],
            "status": "success" | "area_not_found" | "no_results" | "unknown_intent" | "error",
            "intent": str,
            "city": str | None,
            "area": str | None,
            "search_data": dict,
            "message": str
        }
    """
    # Step 1: Send message to local Ollama AI model
    ai_data = understand_request(user_message)

    # Check for AI communication error
    if not isinstance(ai_data, dict) or ai_data.get("error"):
        return {
            "query": user_message,
            "understanding": ai_data if isinstance(ai_data, dict) else {"intent": "unknown"},
            "results": [],
            "status": "error",
            "intent": "unknown",
            "city": None,
            "area": None,
            "search_data": {},
            "message": "Failed to communicate with AI model.",
        }

    intent = ai_data.get("intent", "unknown")
    if intent not in ["property_search", "rental_item_search", "vehicle_search", "helper_search"]:
        return {
            "query": user_message,
            "understanding": ai_data,
            "results": [],
            "status": "unknown_intent",
            "intent": intent,
            "city": None,
            "area": None,
            "search_data": {},
            "message": "Could not identify a search intent. Please specify a home, rental item, vehicle, or helper service.",
        }

    city = ai_data.get("city")
    area = ai_data.get("area")

    # Build search_data preserving all original extracted search filters
    search_data = {
        "intent": intent,
        "city": city,
        "area": area,
        "property_type": ai_data.get("property_type"),
        "max_budget": ai_data.get("max_budget"),
        "category": ai_data.get("category"),
        "item_name": ai_data.get("item_name"),
        "vehicle_type": ai_data.get("vehicle_type"),
        "service_type": ai_data.get("service_type"),
    }

    # Step 2: Execute search with area filter if provided
    if area:
        db_records = _execute_intent_search(intent, ai_data, area=area)
        if db_records is None:
            return {
                "query": user_message,
                "understanding": ai_data,
                "results": [],
                "status": "error",
                "intent": intent,
                "city": city,
                "area": area,
                "search_data": search_data,
                "message": "A database error occurred while retrieving listings.",
            }

        # If no results found in specific area, return area_not_found for confirmation
        if not db_records:
            return {
                "query": user_message,
                "understanding": ai_data,
                "status": "area_not_found",
                "intent": intent,
                "city": city,
                "area": area,
                "results": [],
                "search_data": search_data,
                "message": f"No matching listings found in {area}.",
            }

        return {
            "query": user_message,
            "understanding": ai_data,
            "results": db_records,
            "status": "success",
            "intent": intent,
            "city": city,
            "area": area,
            "search_data": search_data,
            "message": f"Found {len(db_records)} matching listing(s) in {area}.",
        }

    # Step 3: City-wide search (when no area was requested)
    else:
        db_records = _execute_intent_search(intent, ai_data, area=None)
        if db_records is None:
            return {
                "query": user_message,
                "understanding": ai_data,
                "results": [],
                "status": "error",
                "intent": intent,
                "city": city,
                "area": None,
                "search_data": search_data,
                "message": "A database error occurred while retrieving listings.",
            }

        if not db_records:
            return {
                "query": user_message,
                "understanding": ai_data,
                "results": [],
                "status": "no_results",
                "intent": intent,
                "city": city,
                "area": None,
                "search_data": search_data,
                "message": f"No matching listings found in {city}." if city else "No matching listings found.",
            }

        return {
            "query": user_message,
            "understanding": ai_data,
            "results": db_records,
            "status": "success",
            "intent": intent,
            "city": city,
            "area": None,
            "search_data": search_data,
            "message": f"Found {len(db_records)} matching listing(s) in {city}." if city else f"Found {len(db_records)} matching listing(s).",
        }


def search_without_area(search_data: dict) -> dict:
    """
    Performs a city-wide fallback search without the area filter using preserved search_data.
    Keeps all original filters (intent, city, property_type, max_budget, category, item_name,
    vehicle_type, service_type) with area=None.

    Args:
        search_data (dict): Preserved original search parameters.

    Returns:
        dict: Standard structured search result.
    """
    intent = search_data.get("intent", "unknown")
    city = search_data.get("city")

    # Clone search_data and clear area filter
    fallback_data = dict(search_data)
    fallback_data["area"] = None

    db_records = _execute_intent_search(intent, fallback_data, area=None)
    if db_records is None:
        return {
            "status": "error",
            "intent": intent,
            "city": city,
            "area": None,
            "results": [],
            "search_data": fallback_data,
            "message": "A database error occurred while retrieving city-wide listings.",
        }

    if not db_records:
        return {
            "status": "no_results",
            "intent": intent,
            "city": city,
            "area": None,
            "results": [],
            "search_data": fallback_data,
            "message": f"No matching listings found in {city}." if city else "No matching listings found.",
        }

    return {
        "status": "success",
        "intent": intent,
        "city": city,
        "area": None,
        "results": db_records,
        "is_fallback": True,
        "fallback_city": city,
        "search_data": fallback_data,
        "message": f"Found {len(db_records)} matching listing(s) from other areas in {city}." if city else f"Found {len(db_records)} matching listing(s).",
    }


def format_result_item(item: dict, intent: str) -> str:
    """Helper formatter to display database records cleanly in the terminal."""
    if intent == "property_search":
        title = item.get("title", "Property")
        ptype = item.get("property_type", "N/A")
        area = item.get("area", "")
        city = item.get("city", "")
        loc = f"{area}, {city}".strip(", ")
        rent = item.get("monthly_rent")
        beds = item.get("bedrooms")
        bed_str = f" | {beds} BHK" if beds else ""
        if rent is not None:
            rent_str = f"₹{int(rent):,}/month"
        elif item.get("phone"):
            rent_str = f"Contact: {item.get('phone')}"
        else:
            rent_str = "Verified Accommodation Place"
        return f"🏠 {title} ({ptype}) - {loc} | {rent_str}{bed_str}"

    elif intent == "rental_item_search":
        name = item.get("name", "Item")
        category = item.get("category", "N/A")
        area = item.get("area", "")
        city = item.get("city", "")
        loc = f"{area}, {city}".strip(", ")
        rent = item.get("monthly_rent")
        if rent is not None:
            rent_str = f"₹{int(rent):,}/month"
        elif item.get("phone"):
            rent_str = f"Contact: {item.get('phone')}"
        else:
            rent_str = "Rental Agency"
        return f"🛋️ {name} ({category}) - {loc} | {rent_str}"

    elif intent == "vehicle_search":
        name = item.get("name", "Vehicle")
        brand = item.get("brand", "")
        vtype = item.get("vehicle_type", "Vehicle")
        area = item.get("area", "")
        city = item.get("city", "")
        loc = f"{area}, {city}".strip(", ")
        rent = item.get("daily_rent")
        if rent is not None:
            rent_str = f"₹{int(rent):,}/day"
        elif item.get("phone"):
            rent_str = f"Phone: {item.get('phone')}"
        else:
            rent_str = "Contact for price"
        return f"🚗 {name} ({vtype} - {brand}) - {loc} | {rent_str}"

    elif intent == "helper_search":
        name = item.get("name", "Provider")
        stype = item.get("service_type", "Helper")
        area = item.get("area", "")
        city = item.get("city", "")
        loc = f"{area}, {city}".strip(", ")
        phone = item.get("phone", "N/A")
        return f"🔧 {name} ({stype}) - {loc} | Phone: {phone}"

    return json.dumps(item, cls=DecimalEncoder)


def run_pipeline_tests() -> None:
    """Executes search pipeline tests across required user messages."""
    test_messages = [
        "Find an electrician in Whitefield",
        "Find a plumber in Madivala",
        "Find a bike in Koramangala",
        "Find furniture in HSR Layout",
        "Find a flat in Kakkanad",
        "Find a hostel in Edappally",
        "Find an electrician in Bangalore",
        "Find a bike in Kochi",
        "Hello, how are you?",
    ]

    print("=" * 70)
    print("🔍 UrbanEase Search Service Test (City + Area Location Pipeline)")
    print("=" * 70)

    for i, msg in enumerate(test_messages, start=1):
        print(f"\n--- Test {i} ---")
        print("💬 User Message:")
        print(f"   \"{msg}\"")
        print("   ↓")

        search_output = search_from_message(msg)

        ai_understanding = search_output.get("understanding", {})
        print("🤖 AI Understanding:")
        print(json.dumps(ai_understanding, indent=2))
        print("   ↓")

        results = search_output.get("results", [])
        intent = ai_understanding.get("intent", "unknown")
        status = search_output.get("status")

        print(f"📦 Database Results ({len(results)} found | Status: {status}):")
        print(f"   ℹ️ {search_output.get('message')}")

        if status == "area_not_found":
            print(f"   ⚠️ NO AUTOMATIC FALLBACK: Confirmation prompt sent to user.")
            print(f"   🔘 Inline Buttons: [✅ Show other areas] [❌ No thanks]")
            # Simulate user confirmation calling search_without_area
            simulated = search_without_area(search_output.get("search_data", {}))
            print(f"   🔄 If user confirms: {len(simulated.get('results', []))} listings found from other areas in {simulated.get('city')}.")
        elif results:
            display_limit = 5
            for idx, r in enumerate(results[:display_limit], start=1):
                formatted = format_result_item(r, intent)
                print(f"   {idx}. {formatted}")
            if len(results) > display_limit:
                print(f"   ... and {len(results) - display_limit} more listing(s).")

    print("\n" + "=" * 70)
    print("✅ All search service integration tests completed!")
    print("=" * 70)


if __name__ == "__main__":
    run_pipeline_tests()
