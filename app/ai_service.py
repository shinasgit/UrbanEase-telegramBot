import json
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv
import ollama

# Ensure UTF-8 output encoding for terminal on Windows
if sys.platform == "win32":
    try:
        if sys.stdout and sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Model configuration (supports custom model name and custom Ollama host from .env)
MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
ollama_client = ollama.Client(host=OLLAMA_HOST)

# ---------------------------------------------------------------------------
# Location Normalization Knowledge Base
# ---------------------------------------------------------------------------
# Maps lower-cased area names and variations to (canonical_area_name, default_city)
KNOWN_AREAS: dict[str, tuple[str, str]] = {
    # --- Bangalore Areas & Variations ---
    "whitefield": ("Whitefield", "Bangalore"),
    "white field": ("Whitefield", "Bangalore"),
    "koramangala": ("Koramangala", "Bangalore"),
    "hsr layout": ("HSR Layout", "Bangalore"),
    "hsr": ("HSR Layout", "Bangalore"),
    "madivala": ("Madivala", "Bangalore"),
    "madiwala": ("Madivala", "Bangalore"),
    "silk board": ("Silk Board", "Bangalore"),
    "silkboard": ("Silk Board", "Bangalore"),
    "indiranagar": ("Indiranagar", "Bangalore"),
    "indira nagar": ("Indiranagar", "Bangalore"),
    "electronic city": ("Electronic City", "Bangalore"),
    "electroniccity": ("Electronic City", "Bangalore"),
    "ecity": ("Electronic City", "Bangalore"),
    "marathahalli": ("Marathahalli", "Bangalore"),
    "marathalli": ("Marathahalli", "Bangalore"),
    "jayanagar": ("Jayanagar", "Bangalore"),
    "btm layout": ("BTM Layout", "Bangalore"),
    "btm": ("BTM Layout", "Bangalore"),
    "majestic": ("Majestic", "Bangalore"),
    "bellandur": ("Bellandur", "Bangalore"),
    "jp nagar": ("JP Nagar", "Bangalore"),
    "hebbal": ("Hebbal", "Bangalore"),
    "yelahanka": ("Yelahanka", "Bangalore"),
    "rajajinagar": ("Rajajinagar", "Bangalore"),
    "banashankari": ("Banashankari", "Bangalore"),
    "malleshwaram": ("Malleshwaram", "Bangalore"),

    # --- Kochi Areas & Variations ---
    "kakkanad": ("Kakkanad", "Kochi"),
    "edappally": ("Edappally", "Kochi"),
    "edapally": ("Edappally", "Kochi"),
    "kaloor": ("Kaloor", "Kochi"),
    "vyttila": ("Vyttila", "Kochi"),
    "vytilla": ("Vyttila", "Kochi"),
    "fort kochi": ("Fort Kochi", "Kochi"),
    "fortkochi": ("Fort Kochi", "Kochi"),
    "palarivattom": ("Palarivattom", "Kochi"),
    "mg road": ("MG Road", "Kochi"),
    "aluva": ("Aluva", "Kochi"),
    "ernakulam": ("Ernakulam", "Kochi"),
    "thrikkakara": ("Thrikkakara", "Kochi"),
    "marine drive": ("Marine Drive", "Kochi"),
    "kadavanthra": ("Kadavanthra", "Kochi"),
    "kalamassery": ("Kalamassery", "Kochi"),
    "tripunithura": ("Tripunithura", "Kochi"),
}


def normalize_extracted_location(ai_data: dict, user_message: str) -> dict:
    """
    Normalizes city and area information extracted from the user's message:
      1. Normalizes area names (e.g., 'HSR' -> 'HSR Layout', 'White field' -> 'Whitefield').
      2. If an area is provided without a city, determines city automatically (e.g. Whitefield -> Bangalore).
      3. If both city and area are provided, preserves both without overwriting a valid user city.
      4. Detects known areas from the user message if the LLM placed it in 'city' or missed 'area'.
      5. Preserves unknown user-specified areas as title-cased strings.
      6. Ensures the 'area' key is consistently present across all search intents.
    """
    if not isinstance(ai_data, dict):
        return ai_data

    intent = ai_data.get("intent", "unknown")
    if intent == "unknown":
        return ai_data

    raw_city = ai_data.get("city")
    raw_area = ai_data.get("area")
    user_lower = user_message.lower() if user_message else ""

    detected_city: str | None = raw_city.strip() if isinstance(raw_city, str) and raw_city.strip() else None
    detected_area: str | None = raw_area.strip() if isinstance(raw_area, str) and raw_area.strip() else None

    # Edge Case: Model put an area into the 'city' field (e.g. city="Whitefield", area=None)
    if detected_city and detected_city.lower() in KNOWN_AREAS:
        canonical_area, default_city = KNOWN_AREAS[detected_city.lower()]
        detected_area = canonical_area
        detected_city = default_city

    # Hallucination filter: verify detected_area actually corresponds to text in user_message
    if detected_area:
        area_clean = re.sub(r"[^a-zA-Z0-9\s]", "", detected_area.lower())
        area_words = [w for w in area_clean.split() if len(w) > 2]
        # If none of the words from detected_area appear in the user message, it's a prompt hallucination
        if area_words and not any(w in user_lower for w in area_words):
            detected_area = None

    # Detect if user explicitly mentioned a city in their text
    user_specified_city = None
    if re.search(r"\b(bangalore|bengaluru)\b", user_lower):
        user_specified_city = "Bangalore"
    elif re.search(r"\b(kochi|cochin)\b", user_lower):
        user_specified_city = "Kochi"

    # Check if detected_area matches known area dictionary
    if detected_area:
        area_key = detected_area.lower().strip()
        if area_key in KNOWN_AREAS:
            canonical_area, default_city = KNOWN_AREAS[area_key]
            detected_area = canonical_area
            # If user explicitly stated a city, preserve it; otherwise use the known area's city
            detected_city = user_specified_city or default_city
        else:
            # Preserve unknown area names cleanly in Title Case
            detected_area = detected_area.title()
            detected_city = user_specified_city or detected_city
    else:
        # If area was not specified or was cleared, scan user message for known area phrases
        # Sort keys by length descending to match compound names first (e.g. 'electronic city' before 'city')
        for area_key in sorted(KNOWN_AREAS.keys(), key=len, reverse=True):
            pattern = r"\b" + re.escape(area_key) + r"\b"
            if re.search(pattern, user_lower):
                canonical_area, default_city = KNOWN_AREAS[area_key]
                detected_area = canonical_area
                detected_city = user_specified_city or default_city
                break
        else:
            if user_specified_city:
                detected_city = user_specified_city

    # City normalization: ensure it's strictly Bangalore or Kochi if detected
    if detected_city:
        city_lower = detected_city.lower()
        if "bangalore" in city_lower or "bengaluru" in city_lower:
            detected_city = "Bangalore"
        elif "kochi" in city_lower or "cochin" in city_lower:
            detected_city = "Kochi"

    # Scan user message for city if still null
    if not detected_city:
        if re.search(r"\b(bangalore|bengaluru)\b", user_lower):
            detected_city = "Bangalore"
        elif re.search(r"\b(kochi|cochin)\b", user_lower):
            detected_city = "Kochi"

    ai_data["city"] = detected_city
    ai_data["area"] = detected_area

    return ai_data


# System prompt defining the UrbanEase AI extraction rules
SYSTEM_PROMPT = """You are the AI request understanding engine for UrbanEase, a rental and local services platform.
Your task is to analyze user search requests and return ONLY a valid JSON object.

SUPPORTED INTENTS AND JSON SCHEMAS:

1. Property Search:
{
  "intent": "property_search",
  "city": "Kochi" | "Bangalore" | null,
  "area": "<area name if mentioned by user, otherwise null>",
  "property_type": "House" | "Flat" | "PG" | "Hostel" | null,
  "max_budget": <integer number> | null
}

2. Rental Item Search (Appliances & Furniture):
{
  "intent": "rental_item_search",
  "city": "Kochi" | "Bangalore" | null,
  "area": "<area name if mentioned by user, otherwise null>",
  "category": "Appliance" | "Furniture" | null,
  "item_name": "<name of item, e.g. Washing Machine, Refrigerator, Sofa, Bed>" | null
}

3. Vehicle Search:
{
  "intent": "vehicle_search",
  "city": "Kochi" | "Bangalore" | null,
  "area": "<area name if mentioned by user, otherwise null>",
  "vehicle_type": "Bike" | "Car" | null
}

4. Helper Search (Local Service Providers):
{
  "intent": "helper_search",
  "city": "Kochi" | "Bangalore" | null,
  "area": "<area name if mentioned by user, otherwise null>",
  "service_type": "Electrician" | "Plumber" | "Carpenter" | "AC Repair" | "Cleaner" | null
}

5. Unknown / General Conversation:
If the request does not match any of the above categories, return:
{
  "intent": "unknown"
}

LOCATION EXTRACTION AND NORMALIZATION RULES:
- Areas and Cities:
  * Bangalore areas include: Whitefield, Koramangala, HSR Layout, Madivala, Silk Board, Indiranagar, Electronic City, Marathahalli, Jayanagar, BTM Layout, Majestic, Bellandur, JP Nagar, etc.
  * Kochi areas include: Kakkanad, Edappally, Kaloor, Vyttila, Fort Kochi, Palarivattom, MG Road, Aluva, Ernakulam, etc.
  * CRITICAL: If the user only specifies a city (e.g. "in Bangalore" or "in Kochi") and does NOT specify any area, set "area": null. NEVER hallucinate or copy an example area if none was requested.
  * If a user provides an area without a city, determine and set the city automatically (e.g. "Whitefield" -> city: "Bangalore", area: "Whitefield"; "Kakkanad" -> city: "Kochi", area: "Kakkanad").
  * If both city and area are provided (e.g. "Whitefield, Bangalore"), preserve both (city: "Bangalore", area: "Whitefield").
  * Normalize common area variations:
    - "HSR" -> "HSR Layout"
    - "Silkboard" -> "Silk Board"
    - "White field" -> "Whitefield"
    - "Madivala" / "Madiwala" -> "Madivala"
    - "BTM" -> "BTM Layout"
  * Do not restrict to only these areas; preserve any other valid user-specified area as a clean string.
  * If no specific area is mentioned, set "area": null.
  * Cities: Normalize strictly to "Kochi" or "Bangalore". If not specified or unknown, use null.

CATEGORY AND ENTITY NORMALIZATION RULES:
- Property Types: Normalize strictly to "House", "Flat", "PG", or "Hostel".
- Rental Categories: Normalize strictly to "Appliance" or "Furniture".
- Vehicle Types: Normalize strictly to "Bike" or "Car".
- Helper Services: Normalize strictly to "Electrician", "Plumber", "Carpenter", "AC Repair", or "Cleaner".
- Max Budget: Extract numeric value as integer (e.g. 20000). If not specified, use null.
- Use null whenever information is not provided. Do not invent or assume details.
- Output ONLY valid JSON. No explanations, no markdown fences, no conversational text.
"""


def understand_request(user_message: str) -> dict:
    """
    Sends the user's natural language message to the local Ollama Llama 3.2 model.
    Parses the response into a structured Python dictionary.

    Args:
        user_message (str): Natural language query from the user.

    Returns:
        dict: Structured dictionary matching the detected intent schema.
    """
    if not user_message or not user_message.strip():
        return {"intent": "unknown"}

    try:
        response = ollama_client.chat(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ],
            format="json",
            options={"temperature": 0.0},
        )

        content = (
            response.message.content
            if hasattr(response, "message")
            else response["message"]["content"]
        )

        # Parse JSON response into a Python dictionary
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return normalize_extracted_location(parsed, user_message)
            return {"intent": "unknown"}
        except json.JSONDecodeError:
            # Fallback regex extraction in case of unexpected text surrounding JSON
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        return normalize_extracted_location(parsed, user_message)
                except json.JSONDecodeError:
                    pass
            return {"intent": "unknown"}

    except Exception as exc:
        print(f"❌ Error communicating with Ollama AI model: {exc}", file=sys.stderr)
        return {"intent": "unknown", "error": str(exc)}


def test_ai() -> None:
    """Connection test verifying basic Ollama communication."""
    print(f"🔄 Testing basic connection to Ollama model '{MODEL_NAME}'...")
    sample = understand_request("Find an electrician in Whitefield")
    print(f"Sample response: {sample}")


def run_tests() -> None:
    """Runs test cases on the required sample messages and prints results."""
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

    print("=" * 65)
    print(f"🤖 UrbanEase AI Request Understanding Test ({MODEL_NAME})")
    print("=" * 65)

    for i, msg in enumerate(test_messages, start=1):
        print(f"\n--- Test {i} ---")
        print(f"💬 User Message: \"{msg}\"")
        structured_data = understand_request(msg)
        print("📦 Structured Output:")
        print(json.dumps(structured_data, indent=2))

    print("\n" + "=" * 65)
    print("✅ All AI request understanding tests completed!")
    print("=" * 65)


if __name__ == "__main__":
    run_tests()
