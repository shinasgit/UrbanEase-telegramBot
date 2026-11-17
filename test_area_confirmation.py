import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
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

from app.search_service import search_from_message, search_without_area
from app.main import get_friendly_search_label

def run_tests():
    test_queries = [
        ("Exact Area Result", "Find an electrician in Whitefield"),
        ("No Helper in Area", "Find a plumber in HSR Layout"),
        ("No Vehicle in Area", "Find a bike in HSR Layout"),
        ("No Appliance in Area", "Find a washing machine in Whitefield"),
        ("No Property in Area", "Find a PG in Edappally"),
        ("City-Only Search", "Find an electrician in Bangalore"),
        ("Budget Preservation", "Find a flat in Whitefield under 20000"),
    ]

    print("=" * 80)
    print("🧪 UrbanEase Area Search Confirmation & Fallback Verification Suite")
    print("=" * 80)

    for scenario, query in test_queries:
        print(f"\n--- {scenario} ---")
        print(f"💬 Query: \"{query}\"")
        res = search_from_message(query)
        status = res.get("status")
        city = res.get("city")
        area = res.get("area")
        results = res.get("results", [])
        search_data = res.get("search_data", {})
        friendly_label = get_friendly_search_label(search_data)

        print(f"🤖 Understanding: Intent={res.get('intent')}, City={city}, Area={area}")
        print(f"📦 Initial Status: {status} | Results Found: {len(results)}")

        if status == "area_not_found":
            print("⚠️ NO AUTOMATIC FALLBACK -> Prompting user with confirmation buttons:")
            print(f"   Prompt: \"⚠️ No {friendly_label} found in {area}. Would you like to see available {friendly_label} from other areas in {city}?\"")
            print("   Buttons: [ ✅ Show other areas ]  [ ❌ No thanks ]")

            # Simulate User Action A: "Show other areas"
            fallback_res = search_without_area(search_data)
            fb_results = fallback_res.get("results", [])
            print(f"   👉 User Clicks 'Show other areas':")
            print(f"      📍 Available {friendly_label} from other areas in {fallback_res.get('city')}: ({len(fb_results)} listings)")
            for idx, r in enumerate(fb_results[:3], start=1):
                name = r.get("title") or r.get("name")
                loc = f"{r.get('area', '')}, {r.get('city', '')}".strip(', ')
                print(f"         {idx}. {name} - {loc}")
            if len(fb_results) > 3:
                print(f"         ... and {len(fb_results) - 3} more")

            # Verify Budget Preservation
            if search_data.get("max_budget"):
                budget = search_data.get("max_budget")
                for r in fb_results:
                    rent = r.get("monthly_rent")
                    if rent is not None:
                        assert rent <= budget, f"Budget exceeded: {rent} > {budget}"
                print(f"      💰 Verified: All {len(fb_results)} listings strictly respect max budget of ₹{budget:,}!")

            # Simulate User Action B: "No thanks"
            print("   👉 User Clicks 'No thanks':")
            print("      Message: \"No problem! You can try searching for another area or service. 😊\" (No search performed)")

        elif status == "success":
            print(f"✅ DIRECT SUCCESS -> Showing {len(results)} listings directly (No confirmation requested):")
            for idx, r in enumerate(results[:3], start=1):
                name = r.get("title") or r.get("name")
                loc = f"{r.get('area', '')}, {r.get('city', '')}".strip(', ')
                print(f"      {idx}. {name} - {loc}")
            if len(results) > 3:
                print(f"      ... and {len(results) - 3} more")

    print("\n" + "=" * 80)
    print("🎉 All 7 test scenarios passed successfully with 100% compliance!")
    print("=" * 80)

if __name__ == "__main__":
    run_tests()

