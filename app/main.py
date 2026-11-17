import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Import AI Search Service
from app.search_service import search_from_message, search_without_area

# Import database functions
from app.database import (
    get_all_properties,
    get_rental_cities,
    get_rental_items,
    get_service_cities,
    get_service_providers,
    get_unique_cities,
    get_unique_property_types,
    get_unique_service_types,
    get_unique_vehicle_types,
    get_vehicle_cities,
    get_vehicles,
    search_properties,
    search_rental_items_nl,
    search_vehicles_nl,
)

# Ensure UTF-8 output encoding for terminal on Windows
if sys.platform == "win32":
    try:
        if sys.stdout and sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 1. Load environment variables from .env file
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# 2. Validate TELEGRAM_BOT_TOKEN
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("❌ Error: TELEGRAM_BOT_TOKEN is missing or empty in your .env file.", file=sys.stderr)
    print("Please set TELEGRAM_BOT_TOKEN in .env and try again.", file=sys.stderr)
    sys.exit(1)

# 3. Content definitions
WELCOME_TEXT = (
    "🏙️ *Welcome to UrbanEase!*\n\n"
    "I can help you find:\n\n"
    "🏠 Houses, Flats, PGs & Hostels\n"
    "🛋️ Rental Appliances & Furniture\n"
    "🚗 Rental Vehicles\n"
    "🔧 Electricians, Plumbers & Other Helpers\n\n"
    "💡 *Tip:* You can use the buttons below or simply type what you need!\n"
    "_(e.g., 'Find a flat in Kochi under 20000' or 'Need a bike in Bangalore')_"
)

# 4. Budget Range Definitions (Home Search)
BUDGET_CONFIG = {
    "under_5k": {
        "button": "💰 Under ₹5,000",
        "display": "Under ₹5,000",
        "min": None,
        "max": 5000,
    },
    "5k_10k": {
        "button": "💰 ₹5,000 – ₹10,000",
        "display": "₹5,000 – ₹10,000",
        "min": 5000,
        "max": 10000,
    },
    "10k_20k": {
        "button": "💰 ₹10,000 – ₹20,000",
        "display": "₹10,000 – ₹20,000",
        "min": 10000,
        "max": 20000,
    },
    "20k_30k": {
        "button": "💰 ₹20,000 – ₹30,000",
        "display": "₹20,000 – ₹30,000",
        "min": 20000,
        "max": 30000,
    },
    "above_30k": {
        "button": "💰 Above ₹30,000",
        "display": "Above ₹30,000",
        "min": 30000,
        "max": None,
    },
    "none": {
        "button": "📋 No Budget Limit",
        "display": "No Budget Limit",
        "min": None,
        "max": None,
    },
}


# 5. Helpers: Formatting & Icons
def get_property_type_icon(prop_type: str) -> str:
    """Returns an appropriate emoji icon for a given property type."""
    icons = {
        "house": "🏠",
        "flat": "🏢",
        "apartment": "🏢",
        "pg": "🛏️",
        "hostel": "🏨",
        "villa": "🏡",
    }
    return icons.get(prop_type.lower(), "🏢")


def get_rental_item_icon(name: str, category: str) -> str:
    """Returns an appropriate emoji icon based on rental item name and category."""
    n = name.lower()
    if "refrigerator" in n or "fridge" in n or "air conditioner" in n or "ac" in n:
        return "❄️"
    if "tv" in n or "television" in n or "led" in n:
        return "📺"
    if "washing" in n:
        return "🧺"
    if "microwave" in n or "oven" in n:
        return "🍲"
    if "purifier" in n:
        return "💧"
    if "fan" in n:
        return "🌀"
    if "bed" in n:
        return "🛏️"
    if "sofa" in n:
        return "🛋️"
    if "table" in n or "desk" in n:
        return "🪵"
    if "chair" in n:
        return "🪑"
    if "wardrobe" in n or "cupboard" in n:
        return "🚪"
    return "❄️" if category.lower() == "appliance" else "🛋️"


def get_vehicle_type_icon(vtype: str) -> str:
    """Returns an appropriate emoji icon for a given vehicle type."""
    return "🏍️" if vtype.lower() == "bike" else "🚗"


def get_service_icon(service_type: str) -> str:
    """Returns an appropriate emoji icon for a given service type."""
    icons = {
        "electrician": "⚡",
        "plumber": "🚰",
        "carpenter": "🔨",
        "ac repair": "❄️",
        "cleaner": "🧹",
        "cleaning": "🧹",
    }
    return icons.get(service_type.lower(), "🔧")


def format_search_results(
    properties: list[dict],
    city: str,
    prop_type: str,
    budget_label: str,
) -> str:
    """Formats property listings with a summary header into clean markdown."""
    type_display = "All Types" if prop_type.upper() == "ALL" else prop_type

    summary = (
        "🏠 *Search Results*\n\n"
        f"📍 *City:* {city}\n"
        f"🏢 *Type:* {type_display}\n"
        f"💰 *Budget:* {budget_label}\n"
    )

    if not properties:
        return (
            f"{summary}\n"
            "😔 Sorry, no properties match your search.\n\n"
            "Try changing your budget, property type, or city."
        )

    cards = []
    for prop in properties:
        title = prop.get("title", "Untitled Property")
        p_type = prop.get("property_type", "Property")
        area = prop.get("area", "")
        prop_city = prop.get("city", "")
        location = f"{area}, {prop_city}".strip(", ") or "Location not specified"

        rent = prop.get("monthly_rent")
        rent_text = f"₹{int(rent):,}" if rent is not None else "Contact for price"

        bedrooms = prop.get("bedrooms")
        bedroom_line = f"🛏️ *Bedrooms:* {bedrooms}\n" if bedrooms is not None else ""

        description = prop.get("description") or "No description available."

        card = (
            f"🏠 *{title}*\n\n"
            f"🏢 *Type:* {p_type}\n"
            f"📍 *Location:* {location}\n"
            f"💰 *Rent:* {rent_text} / month\n"
            f"{bedroom_line}"
            f"📝 *Description:* {description}"
        )
        cards.append(card)

    divider = "\n\n────────────────────\n\n"
    return summary + "\n" + divider.join(cards)


def format_rental_items_results(
    items: list[dict],
    category: str,
    city: str,
) -> str:
    """Formats rental items listings into clean markdown."""
    summary = (
        "🛋️ *Available Rental Items*\n\n"
        f"📍 *City:* {city}\n"
        f"📦 *Category:* {category}\n"
    )

    if not items:
        return (
            f"{summary}\n"
            "😔 Sorry, no rental items are currently available for this selection.\n\n"
            "Please try another category or city."
        )

    cards = []
    for item in items:
        name = item.get("name", "Rental Item")
        cat = item.get("category", category)
        area = item.get("area", "")
        item_city = item.get("city", "")
        location = f"{area}, {item_city}".strip(", ") or "Location not specified"

        rent = item.get("monthly_rent")
        rent_text = f"₹{int(rent):,}" if rent is not None else "Contact for price"

        description = item.get("description") or "No description available."
        icon = get_rental_item_icon(name, cat)

        card = (
            f"{icon} *{name}*\n"
            f"📦 *Category:* {cat}\n"
            f"📍 *Location:* {location}\n"
            f"💰 *Rent:* {rent_text} / month\n"
            f"📝 *Description:* {description}"
        )
        cards.append(card)

    divider = "\n\n────────────────────\n\n"
    return summary + "\n" + divider.join(cards)


def format_vehicles_results(
    vehicles: list[dict],
    vehicle_type: str,
    city: str,
) -> str:
    """Formats vehicle listings into clean markdown."""
    summary = (
        "🚗 *Available Rental Vehicles*\n\n"
        f"📍 *City:* {city}\n"
        f"🚘 *Type:* {vehicle_type}\n"
    )

    if not vehicles:
        return (
            f"{summary}\n"
            "😔 Sorry, no vehicles are currently available for this selection.\n\n"
            "Please try another vehicle type or city."
        )

    cards = []
    for v in vehicles:
        name = v.get("name", "Vehicle Listing")
        brand = v.get("brand", "N/A")
        v_type = v.get("vehicle_type", vehicle_type)
        area = v.get("area", "")
        item_city = v.get("city", "")
        location = f"{area}, {item_city}".strip(", ") or "Location not specified"

        rent = v.get("daily_rent")
        rent_text = f"₹{int(rent):,}" if rent is not None else "Contact for price"

        description = v.get("description") or "No description available."
        icon = get_vehicle_type_icon(v_type)

        card = (
            f"{icon} *{name}*\n"
            f"🏷️ *Brand:* {brand}\n"
            f"🚘 *Type:* {v_type}\n"
            f"📍 *Location:* {location}\n"
            f"💰 *Rent:* {rent_text} / day\n"
            f"📝 *Description:* {description}"
        )
        cards.append(card)

    divider = "\n\n────────────────────\n\n"
    return summary + "\n" + divider.join(cards)


def format_helpers_results(
    helpers: list[dict],
    service_type: str,
    city: str,
) -> str:
    """Formats service provider listings into clean markdown."""
    plural_service = f"{service_type}s" if not service_type.endswith("s") else service_type
    summary = (
        f"🔧 *Available {plural_service}*\n\n"
        f"📍 *City:* {city}\n"
        f"🔧 *Service:* {service_type}\n"
    )

    if not helpers:
        return (
            f"{summary}\n"
            "😔 Sorry, no helpers are currently available for this selection.\n\n"
            "Please try another service or city."
        )

    cards = []
    for h in helpers:
        name = h.get("name", "Service Provider")
        stype = h.get("service_type", service_type)
        area = h.get("area", "")
        item_city = h.get("city", "")
        location = f"{area}, {item_city}".strip(", ") or "Location not specified"
        phone = h.get("phone") or "Contact desk"
        description = h.get("description") or "No description available."
        icon = get_service_icon(stype)

        card = (
            f"{icon} *{name}*\n"
            f"🏷️ *Service:* {stype}\n"
            f"📍 *Location:* {location}\n"
            f"📞 *Contact:* {phone}\n"
            f"📝 *Description:* {description}"
        )
        cards.append(card)

    divider = "\n\n────────────────────\n\n"
    return summary + "\n" + divider.join(cards)


# 6. Natural Language Processing (Rule-based Keyword Matching)
def extract_city(text: str) -> str | None:
    """Extracts known supported cities from user text using case-insensitive matching."""
    if re.search(r"\b(kochi|cochin)\b", text, re.IGNORECASE):
        return "Kochi"
    if re.search(r"\b(bangalore|bengaluru)\b", text, re.IGNORECASE):
        return "Bangalore"
    return None


def extract_budget(text: str) -> float | None:
    """Extracts numerical budget from phrases like 'under 20000', 'below 15k', etc."""
    pattern = r"(?:under|below|less than|within|up to|max(?:imum)?|budget of|budget)\s*(?:₹|rs\.?)?\s*(\d+(?:,\d+)?|\d+k)"
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        raw_val = m.group(1).replace(",", "").lower()
        if raw_val.endswith("k"):
            try:
                return float(raw_val[:-1]) * 1000
            except ValueError:
                pass
        else:
            try:
                return float(raw_val)
            except ValueError:
                pass
    return None


def detect_user_intent(text: str) -> dict | None:
    """
    Analyzes natural language text to detect intent (Home, Rental Item, Vehicle, Helper)
    and extracts relevant query parameters.
    """
    t = text.lower()

    # 1. Helper Search Keywords
    helper_map = {
        "electrician": "Electrician",
        "plumber": "Plumber",
        "carpenter": "Carpenter",
        "ac repair": "AC Repair",
        "ac service": "AC Repair",
        "cleaner": "Cleaner",
        "cleaning": "Cleaner",
        "maid": "Cleaner",
    }
    for kw, stype in helper_map.items():
        if kw in t:
            return {"intent": "helper", "service_type": stype, "keyword": kw.title()}

    # 2. Rental Vehicles Keywords
    if "honda city" in t:
        return {"intent": "vehicle", "vehicle_type": "Car", "keyword": "Honda City"}

    vehicle_map = {
        "bike": "Bike",
        "scooter": "Bike",
        "motorcycle": "Bike",
        "activa": "Bike",
        "pulsar": "Bike",
        "jupiter": "Bike",
        "r15": "Bike",
        "hunter": "Bike",
        "access": "Bike",
        "car": "Car",
        "swift": "Car",
        "i20": "Car",
        "nexon": "Car",
        "creta": "Car",
        "thar": "Car",
        "baleno": "Car",
        "vehicle": None,
    }
    for kw, vtype in vehicle_map.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", t):
            return {"intent": "vehicle", "vehicle_type": vtype, "keyword": kw.title()}

    # 3. Rental Appliances & Furniture Keywords
    appliances = [
        ("washing machine", "Washing Machine"),
        ("refrigerator", "Refrigerator"),
        ("fridge", "Refrigerator"),
        ("microwave", "Microwave"),
        ("oven", "Microwave"),
        ("tv", "TV"),
        ("television", "TV"),
        ("water purifier", "Water Purifier"),
        ("purifier", "Water Purifier"),
        ("ceiling fan", "Fan"),
        ("fan", "Fan"),
        ("air conditioner", "Air Conditioner"),
        ("ac", "Air Conditioner"),
        ("appliance", None),
        ("appliances", None),
    ]
    for phrase, item_name in appliances:
        if re.search(r"\b" + re.escape(phrase) + r"\b", t):
            return {"intent": "rental_item", "category": "Appliance", "item_keyword": item_name}

    furniture = [
        ("single bed", "Bed"),
        ("double bed", "Bed"),
        ("bed", "Bed"),
        ("sofa", "Sofa"),
        ("study table", "Table"),
        ("dining table", "Table"),
        ("table", "Table"),
        ("office chair", "Chair"),
        ("chair", "Chair"),
        ("wardrobe", "Wardrobe"),
        ("cupboard", "Wardrobe"),
        ("furniture", None),
    ]
    for phrase, item_name in furniture:
        if re.search(r"\b" + re.escape(phrase) + r"\b", t):
            return {"intent": "rental_item", "category": "Furniture", "item_keyword": item_name}

    # 4. Property Search Keywords
    prop_map = {
        "flat": "Flat",
        "apartment": "Flat",
        "pg": "PG",
        "paying guest": "PG",
        "hostel": "Hostel",
        "house": "House",
        "home": "House",
        "villa": "House",
        "room": None,
    }
    for kw, ptype in prop_map.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", t):
            return {"intent": "property", "property_type": ptype, "keyword": kw.title()}

    return None


# 7. Keyboards
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Builds the main menu inline keyboard."""
    keyboard = [
        [InlineKeyboardButton("🏠 Find a Home", callback_data="find_home")],
        [InlineKeyboardButton("🛋️ Rental Appliances", callback_data="rental_appliances")],
        [InlineKeyboardButton("🚗 Rental Vehicles", callback_data="rental_vehicles")],
        [InlineKeyboardButton("🔧 Find a Helper", callback_data="find_helper")],
    ]
    return InlineKeyboardMarkup(keyboard)


# Keyboards for Home Search
def get_cities_keyboard(cities: list[str]) -> InlineKeyboardMarkup:
    """Builds an inline keyboard displaying available cities for Home Search."""
    keyboard = []
    for city in cities:
        keyboard.append([InlineKeyboardButton(f"📍 {city}", callback_data=f"city_{city}")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_property_types_keyboard(property_types: list[str]) -> InlineKeyboardMarkup:
    """Builds an inline keyboard displaying property types dynamically."""
    keyboard = []
    for ptype in property_types:
        icon = get_property_type_icon(ptype)
        keyboard.append([InlineKeyboardButton(f"{icon} {ptype}", callback_data=f"type_{ptype}")])

    keyboard.append([InlineKeyboardButton("📋 Show All Properties", callback_data="type_ALL")])
    keyboard.append([InlineKeyboardButton("🔙 Back to City Selection", callback_data="find_home")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_budget_keyboard() -> InlineKeyboardMarkup:
    """Builds the monthly budget selection inline keyboard."""
    keyboard = [
        [InlineKeyboardButton(BUDGET_CONFIG["under_5k"]["button"], callback_data="bgt_under_5k")],
        [InlineKeyboardButton(BUDGET_CONFIG["5k_10k"]["button"], callback_data="bgt_5k_10k")],
        [InlineKeyboardButton(BUDGET_CONFIG["10k_20k"]["button"], callback_data="bgt_10k_20k")],
        [InlineKeyboardButton(BUDGET_CONFIG["20k_30k"]["button"], callback_data="bgt_20k_30k")],
        [InlineKeyboardButton(BUDGET_CONFIG["above_30k"]["button"], callback_data="bgt_above_30k")],
        [InlineKeyboardButton(BUDGET_CONFIG["none"]["button"], callback_data="bgt_none")],
        [InlineKeyboardButton("🔙 Back to Property Type Selection", callback_data="back_to_types")],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_home_results_keyboard() -> InlineKeyboardMarkup:
    """Builds navigation buttons shown under home search results."""
    keyboard = [
        [InlineKeyboardButton("💰 Change Budget", callback_data="back_to_budget")],
        [InlineKeyboardButton("🏢 Change Property Type", callback_data="back_to_types")],
        [InlineKeyboardButton("📍 Change City", callback_data="find_home")],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


# Keyboards for Rental Appliances & Furniture
def get_rental_categories_keyboard() -> InlineKeyboardMarkup:
    """Builds keyboard for rental category selection."""
    keyboard = [
        [InlineKeyboardButton("❄️ Appliances", callback_data="rentcat_Appliance")],
        [InlineKeyboardButton("🛋️ Furniture", callback_data="rentcat_Furniture")],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_rental_cities_keyboard(cities: list[str]) -> InlineKeyboardMarkup:
    """Builds keyboard for selecting cities with available rental items."""
    keyboard = []
    for city in cities:
        keyboard.append([InlineKeyboardButton(f"📍 {city}", callback_data=f"rentcity_{city}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Category Selection", callback_data="rental_appliances")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_rental_results_keyboard(category: str) -> InlineKeyboardMarkup:
    """Builds navigation buttons shown under rental items results."""
    keyboard = [
        [InlineKeyboardButton("📍 Change City", callback_data=f"rentcat_{category}")],
        [InlineKeyboardButton("🔙 Back to Category Selection", callback_data="rental_appliances")],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


# Keyboards for Rental Vehicles
def get_vehicle_types_keyboard(vehicle_types: list[str]) -> InlineKeyboardMarkup:
    """Builds keyboard for vehicle type selection."""
    keyboard = []
    for vtype in vehicle_types:
        icon = get_vehicle_type_icon(vtype)
        keyboard.append([InlineKeyboardButton(f"{icon} {vtype}", callback_data=f"vehtype_{vtype}")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_vehicle_cities_keyboard(cities: list[str]) -> InlineKeyboardMarkup:
    """Builds keyboard for selecting cities with available rental vehicles."""
    keyboard = []
    for city in cities:
        keyboard.append([InlineKeyboardButton(f"📍 {city}", callback_data=f"vehcity_{city}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Vehicle Type Selection", callback_data="rental_vehicles")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_vehicle_results_keyboard(vehicle_type: str) -> InlineKeyboardMarkup:
    """Builds navigation buttons shown under vehicle results."""
    keyboard = [
        [InlineKeyboardButton("📍 Change City", callback_data=f"vehtype_{vehicle_type}")],
        [InlineKeyboardButton("🔙 Back to Vehicle Type Selection", callback_data="rental_vehicles")],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


# Keyboards for Find a Helper (Service Providers)
def get_service_types_keyboard(service_types: list[str]) -> InlineKeyboardMarkup:
    """Builds keyboard for helper service selection."""
    keyboard = []
    for stype in service_types:
        icon = get_service_icon(stype)
        keyboard.append([InlineKeyboardButton(f"{icon} {stype}", callback_data=f"srvtype_{stype}")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_service_cities_keyboard(cities: list[str]) -> InlineKeyboardMarkup:
    """Builds keyboard for selecting cities with available helpers."""
    keyboard = []
    for city in cities:
        keyboard.append([InlineKeyboardButton(f"📍 {city}", callback_data=f"srvcity_{city}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Service Selection", callback_data="find_helper")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_service_results_keyboard(service_type: str) -> InlineKeyboardMarkup:
    """Builds navigation buttons shown under helper results."""
    keyboard = [
        [InlineKeyboardButton("📍 Change City", callback_data=f"srvtype_{service_type}")],
        [InlineKeyboardButton("🔙 Back to Service Selection", callback_data="find_helper")],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_nl_city_prompt_keyboard() -> InlineKeyboardMarkup:
    """Builds keyboard asking user to pick a city for their natural language search."""
    keyboard = [
        [
            InlineKeyboardButton("📍 Kochi", callback_data="nlcity_Kochi"),
            InlineKeyboardButton("📍 Bangalore", callback_data="nlcity_Bangalore"),
        ],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Builds a simple back-to-menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# 8. Helper Screen Renderers
async def show_property_types_screen(query, selected_city: str) -> None:
    """Renders the property type selection screen for a given city."""
    property_types = get_unique_property_types()
    if property_types is None:
        await query.edit_message_text(
            text=f"⚠️ *Unable to retrieve property types for {selected_city} right now.*\n\nPlease try again.",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    prompt_text = (
        "🏠 *Find Your Home*\n\n"
        f"📍 *Selected City:* {selected_city}\n\n"
        "What type of property are you looking for?"
    )
    await query.edit_message_text(
        text=prompt_text,
        reply_markup=get_property_types_keyboard(property_types),
        parse_mode=ParseMode.MARKDOWN,
    )


async def show_budget_screen(query, city: str, prop_type: str) -> None:
    """Renders the budget selection screen."""
    type_display = "All Types" if prop_type.upper() == "ALL" else prop_type
    prompt_text = (
        "💰 *What's your monthly budget?*\n\n"
        f"📍 *City:* {city}\n"
        f"🏢 *Property Type:* {type_display}\n\n"
        "Select your preferred budget range below:"
    )
    await query.edit_message_text(
        text=prompt_text,
        reply_markup=get_budget_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def show_rental_cities_screen(query, category: str) -> None:
    """Renders the city selection screen for a selected rental category."""
    cities = get_rental_cities(category)
    if cities is None:
        await query.edit_message_text(
            text="⚠️ *Unable to retrieve cities right now.*\n\nPlease try again in a few moments.",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not cities:
        await query.edit_message_text(
            text=f"😔 Sorry, no available {category.lower()}s found in any city right now.",
            reply_markup=get_rental_categories_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    prompt_text = (
        "📍 *Select your city*\n\n"
        f"📦 *Category:* {category}\n\n"
        "Choose a city to explore available items:"
    )
    await query.edit_message_text(
        text=prompt_text,
        reply_markup=get_rental_cities_keyboard(cities),
        parse_mode=ParseMode.MARKDOWN,
    )


async def show_vehicle_cities_screen(query, vehicle_type: str) -> None:
    """Renders the city selection screen for a selected vehicle type."""
    cities = get_vehicle_cities(vehicle_type)
    if cities is None:
        await query.edit_message_text(
            text="⚠️ *Unable to retrieve cities right now.*\n\nPlease try again in a few moments.",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not cities:
        await query.edit_message_text(
            text=f"😔 Sorry, no available {vehicle_type.lower()}s found in any city right now.",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    icon = get_vehicle_type_icon(vehicle_type)
    prompt_text = (
        "📍 *Select your city*\n\n"
        f"{icon} *Vehicle Type:* {vehicle_type}\n\n"
        "Choose a city to explore available vehicles:"
    )
    await query.edit_message_text(
        text=prompt_text,
        reply_markup=get_vehicle_cities_keyboard(cities),
        parse_mode=ParseMode.MARKDOWN,
    )


async def show_service_cities_screen(query, service_type: str) -> None:
    """Renders the city selection screen for a selected helper service."""
    cities = get_service_cities(service_type)
    if cities is None:
        await query.edit_message_text(
            text="⚠️ *Unable to retrieve cities right now.*\n\nPlease try again in a few moments.",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not cities:
        await query.edit_message_text(
            text=f"😔 Sorry, no available {service_type.lower()}s found in any city right now.",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    icon = get_service_icon(service_type)
    prompt_text = (
        "📍 *Select your city*\n\n"
        f"{icon} *Service:* {service_type}\n\n"
        "Choose a city to explore available helpers:"
    )
    await query.edit_message_text(
        text=prompt_text,
        reply_markup=get_service_cities_keyboard(cities),
        parse_mode=ParseMode.MARKDOWN,
    )


# 9. Natural Language Search Execution Handler
def execute_natural_language_search(intent_data: dict, city: str, budget: float | None = None) -> str:
    """
    Executes PostgreSQL query based on detected intent, city, and optional budget.
    Returns formatted markdown message string ready for Telegram.
    """
    intent = intent_data.get("intent")

    # --- Case 1: Properties ---
    if intent == "property":
        prop_type = intent_data.get("property_type")
        budget_str = f"₹{int(budget):,}" if budget is not None else "No Limit"
        looking_for = prop_type if prop_type else "Homes & Properties"

        header = (
            "🔍 *Search Results*\n\n"
            f"📍 *City:* {city}\n"
            f"🏠 *Looking for:* {looking_for}\n"
            f"💰 *Maximum Budget:* {budget_str}\n"
        )

        properties = search_properties(
            city=city,
            property_type=prop_type,
            max_budget=budget,
        )

        if properties is None:
            return (
                f"{header}\n"
                "⚠️ *Database Error:* Unable to retrieve listings right now. Please try again."
            )
        if not properties:
            return (
                f"{header}\n"
                "😔 Sorry, no properties match your search.\n\n"
                "Try changing your budget, property type, or city."
            )

        cards = []
        for prop in properties:
            title = prop.get("title", "Untitled Property")
            p_type = prop.get("property_type", "Property")
            area = prop.get("area", "")
            prop_city = prop.get("city", "")
            location = f"{area}, {prop_city}".strip(", ") or "Location not specified"
            rent = prop.get("monthly_rent")
            rent_text = f"₹{int(rent):,}" if rent is not None else "Contact for price"
            bedrooms = prop.get("bedrooms")
            bedroom_line = f"🛏️ *Bedrooms:* {bedrooms}\n" if bedrooms is not None else ""
            desc = prop.get("description") or "No description available."

            card = (
                f"🏠 *{title}*\n\n"
                f"🏢 *Type:* {p_type}\n"
                f"📍 *Location:* {location}\n"
                f"💰 *Rent:* {rent_text} / month\n"
                f"{bedroom_line}"
                f"📝 *Description:* {desc}"
            )
            cards.append(card)

        divider = "\n\n────────────────────\n\n"
        return header + "\n" + divider.join(cards)

    # --- Case 2: Vehicles ---
    elif intent == "vehicle":
        v_type = intent_data.get("vehicle_type")
        v_kw = intent_data.get("keyword")
        looking_for = v_type if v_type else (v_kw if v_kw else "Rental Vehicles")

        header = (
            "🔍 *Search Results*\n\n"
            f"📍 *City:* {city}\n"
            f"🚗 *Looking for:* {looking_for}\n"
        )

        vehicles = search_vehicles_nl(
            city=city,
            vehicle_type=v_type,
            vehicle_keyword=v_kw,
        )

        if vehicles is None:
            return (
                f"{header}\n"
                "⚠️ *Database Error:* Unable to retrieve vehicles right now. Please try again."
            )
        if not vehicles:
            return (
                f"{header}\n"
                "😔 Sorry, no vehicles are currently available for this selection.\n\n"
                "Please try another vehicle type or city."
            )

        cards = []
        for v in vehicles:
            name = v.get("name", "Vehicle Listing")
            brand = v.get("brand", "N/A")
            veh_type = v.get("vehicle_type", v_type or "Vehicle")
            area = v.get("area", "")
            item_city = v.get("city", "")
            location = f"{area}, {item_city}".strip(", ") or "Location not specified"
            rent = v.get("daily_rent")
            rent_text = f"₹{int(rent):,}" if rent is not None else "Contact for price"
            desc = v.get("description") or "No description available."
            icon = get_vehicle_type_icon(veh_type)

            card = (
                f"{icon} *{name}*\n"
                f"🏷️ *Brand:* {brand}\n"
                f"🚘 *Type:* {veh_type}\n"
                f"📍 *Location:* {location}\n"
                f"💰 *Rent:* {rent_text} / day\n"
                f"📝 *Description:* {desc}"
            )
            cards.append(card)

        divider = "\n\n────────────────────\n\n"
        return header + "\n" + divider.join(cards)

    # --- Case 3: Rental Appliances & Furniture ---
    elif intent == "rental_item":
        category = intent_data.get("category")
        item_kw = intent_data.get("item_keyword")
        looking_for = item_kw if item_kw else (category if category else "Rental Item")

        header = (
            "🔍 *Search Results*\n\n"
            f"📍 *City:* {city}\n"
            f"🛋️ *Looking for:* {looking_for}\n"
        )

        items = search_rental_items_nl(
            city=city,
            category=category,
            item_keyword=item_kw,
        )

        if items is None:
            return (
                f"{header}\n"
                "⚠️ *Database Error:* Unable to retrieve items right now. Please try again."
            )
        if not items:
            return (
                f"{header}\n"
                "😔 Sorry, no rental items are currently available for this selection.\n\n"
                "Please try another category or city."
            )

        cards = []
        for it in items:
            name = it.get("name", "Rental Item")
            cat = it.get("category", category or "Item")
            area = it.get("area", "")
            item_city = it.get("city", "")
            location = f"{area}, {item_city}".strip(", ") or "Location not specified"
            rent = it.get("monthly_rent")
            rent_text = f"₹{int(rent):,}" if rent is not None else "Contact for price"
            desc = it.get("description") or "No description available."
            icon = get_rental_item_icon(name, cat)

            card = (
                f"{icon} *{name}*\n"
                f"📦 *Category:* {cat}\n"
                f"📍 *Location:* {location}\n"
                f"💰 *Rent:* {rent_text} / month\n"
                f"📝 *Description:* {desc}"
            )
            cards.append(card)

        divider = "\n\n────────────────────\n\n"
        return header + "\n" + divider.join(cards)

    # --- Case 4: Helper (Service Providers) ---
    elif intent == "helper":
        stype = intent_data.get("service_type")
        plural = f"{stype}s" if not stype.endswith("s") else stype

        header = (
            f"🔍 *Search Results*\n\n"
            f"📍 *City:* {city}\n"
            f"🔧 *Looking for:* {stype}\n"
        )

        helpers = get_service_providers(service_type=stype, city=city)

        if helpers is None:
            return (
                f"{header}\n"
                "⚠️ *Database Error:* Unable to retrieve helpers right now. Please try again."
            )
        if not helpers:
            return (
                f"{header}\n"
                "😔 Sorry, no helpers are currently available for this selection.\n\n"
                "Please try another service or city."
            )

        cards = []
        for h in helpers:
            name = h.get("name", "Service Provider")
            area = h.get("area", "")
            item_city = h.get("city", "")
            location = f"{area}, {item_city}".strip(", ") or "Location not specified"
            phone = h.get("phone") or "Contact desk"
            desc = h.get("description") or "No description available."
            icon = get_service_icon(stype)

            card = (
                f"{icon} *{name}*\n"
                f"🏷️ *Service:* {stype}\n"
                f"📍 *Location:* {location}\n"
                f"📞 *Contact:* {phone}\n"
                f"📝 *Description:* {desc}"
            )
            cards.append(card)

        divider = "\n\n────────────────────\n\n"
        return header + "\n" + divider.join(cards)

    return "🤔 I couldn't understand what you're looking for."


def get_friendly_search_label(search_data: dict) -> str:
    """Returns a natural plural label like 'plumbers', 'washing machines', 'bikes', 'PGs'."""
    intent = search_data.get("intent")
    if intent == "helper_search":
        st = search_data.get("service_type")
        if not st:
            return "service providers"
        if st.lower() == "ac repair":
            return "AC repair specialists"
        if st.lower().endswith("s"):
            return f"{st.lower()} providers"
        return f"{st.lower()}s"

    elif intent == "property_search":
        pt = search_data.get("property_type")
        if pt:
            if pt.upper() == "PG":
                return "PGs"
            if pt.lower() == "flat":
                return "flats"
            if pt.lower() == "house":
                return "houses"
            if pt.lower() == "hostel":
                return "hostels"
            return f"{pt.lower()} properties"
        return "properties"

    elif intent == "rental_item_search":
        item_name = search_data.get("item_name")
        if item_name:
            il = item_name.lower()
            if il.endswith("s"):
                return il
            return f"{il}s"
        cat = search_data.get("category")
        if cat and cat.lower() == "furniture":
            return "furniture items"
        elif cat and cat.lower() == "appliance":
            return "appliances"
        return "rental items"

    elif intent == "vehicle_search":
        vt = search_data.get("vehicle_type")
        if vt and vt.lower() == "bike":
            return "bikes"
        elif vt and vt.lower() == "car":
            return "cars"
        return "vehicles"

    return "listings"


def get_area_fallback_keyboard() -> InlineKeyboardMarkup:
    """Builds inline keyboard asking whether to show results from other areas in the city."""
    keyboard = [
        [InlineKeyboardButton("✅ Show other areas", callback_data="show_other_areas")],
        [InlineKeyboardButton("❌ No thanks", callback_data="cancel_area_fallback")],
    ]
    return InlineKeyboardMarkup(keyboard)


# 10. AI-Powered Natural Language Search & Formatting
def format_ai_search_results(
    understanding: dict,
    results: list[dict],
    search_output: dict | None = None,
) -> str:
    """
    Formats PostgreSQL search results returned from search_from_message()
    into clean, user-friendly markdown for Telegram.
    """
    intent = understanding.get("intent", "unknown")
    cards = []

    header = ""
    if search_output:
        if search_output.get("search_area") and not search_output.get("is_fallback"):
            s_area = search_output.get("search_area")
            header = f"📍 *Listings in {s_area}:*\n\n"

    for item in results:
        # 1. Properties
        if intent == "property_search":
            title = item.get("title", "Property Listing")
            ptype = item.get("property_type", "Property")
            area = item.get("area", "")
            city = item.get("city", "")
            location = f"{area}, {city}".strip(", ") or "Location not specified"
            rent = item.get("monthly_rent")
            rent_text = f"₹{int(rent):,}/month" if rent is not None else "Contact for price"
            bedrooms = item.get("bedrooms")
            bedroom_line = f"🛏️ Bedrooms: {bedrooms}\n" if bedrooms is not None else ""
            description = (item.get("description") or "").strip()
            desc_line = f"\n{description}" if description else ""
            icon = get_property_type_icon(ptype)

            card = (
                f"{icon} *{title}*\n\n"
                f"📍 {location}\n"
                f"🏢 Type: {ptype}\n"
                f"💰 Rent: {rent_text}\n"
                f"{bedroom_line}"
                f"{desc_line}"
            )
            cards.append(card)

        # 2. Vehicles
        elif intent == "vehicle_search":
            name = item.get("name", "Vehicle Listing")
            brand = item.get("brand", "N/A")
            vtype = item.get("vehicle_type", "Vehicle")
            area = item.get("area", "")
            city = item.get("city", "")
            location = f"{area}, {city}".strip(", ") or "Location not specified"
            rent = item.get("daily_rent")
            rent_text = f"₹{int(rent):,}/day" if rent is not None else "Contact for price"
            description = (item.get("description") or "").strip()
            desc_line = f"\n{description}" if description else ""
            icon = get_vehicle_type_icon(vtype)

            card = (
                f"{icon} *{name}*\n\n"
                f"📍 {location}\n"
                f"🚘 Type: {vtype}\n"
                f"🏷️ Brand: {brand}\n"
                f"💰 Rent: {rent_text}\n"
                f"{desc_line}"
            )
            cards.append(card)

        # 3. Rental Items (Appliances / Furniture)
        elif intent == "rental_item_search":
            name = item.get("name", "Rental Item")
            cat = item.get("category", "Item")
            area = item.get("area", "")
            city = item.get("city", "")
            location = f"{area}, {city}".strip(", ") or "Location not specified"
            rent = item.get("monthly_rent")
            rent_text = f"₹{int(rent):,}/month" if rent is not None else "Contact for price"
            description = (item.get("description") or "").strip()
            desc_line = f"\n{description}" if description else ""
            icon = get_rental_item_icon(name, cat)

            card = (
                f"{icon} *{name}*\n\n"
                f"📍 {location}\n"
                f"📦 Category: {cat}\n"
                f"💰 Rent: {rent_text}\n"
                f"{desc_line}"
            )
            cards.append(card)

        # 4. Helpers (Service Providers)
        elif intent == "helper_search":
            name = item.get("name", "Service Provider")
            stype = item.get("service_type", "Helper")
            area = item.get("area", "")
            city = item.get("city", "")
            location = f"{area}, {city}".strip(", ") or "Location not specified"
            phone = item.get("phone") or "Contact desk"
            description = (item.get("description") or "").strip()
            desc_line = f"\n{description}" if description else ""
            icon = get_service_icon(stype)

            card = (
                f"{icon} *{name}*\n\n"
                f"📍 {location}\n"
                f"🏷️ Service: {stype}\n"
                f"📞 Contact: {phone}\n"
                f"{desc_line}"
            )
            cards.append(card)

    divider = "\n\n────────────────────\n\n"
    return header + divider.join(cards)


async def handle_natural_language_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles freeform text messages sent by the user using the AI Search Service:
      Telegram Message -> search_from_message() -> Ollama AI -> PostgreSQL -> Formatted Telegram reply.
    """
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()

    # Indicate typing state in Telegram while AI & database query executes
    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    # Call AI search service with error protection
    try:
        search_output = search_from_message(user_text)
    except Exception as exc:
        print(f"❌ Error during AI search processing: {exc}", file=sys.stderr)
        await update.message.reply_text(
            text=(
                "⚠️ *Something went wrong while processing your request.*\n\n"
                "Please try again in a moment, or use the menu buttons below."
            ),
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status = search_output.get("status")
    understanding = search_output.get("understanding", {})
    results = search_output.get("results", [])

    # Case 1: Unknown intent or general conversation
    if status == "unknown_intent" or understanding.get("intent") == "unknown":
        unknown_message = (
            "🏙️ *I can help you find:*\n\n"
            "🏠 Houses, Flats, PGs & Hostels\n"
            "🛋️ Rental Appliances & Furniture\n"
            "🚗 Rental Vehicles\n"
            "🔧 Electricians, Plumbers & Other Helpers\n\n"
            "Try a message like:\n"
            '"I need a flat in Kochi under 20000"'
        )
        await update.message.reply_text(
            text=unknown_message,
            reply_markup=get_back_keyboard(),
        )
        return

    # Case 2: AI communication or database error
    if status == "error":
        await update.message.reply_text(
            text=(
                "⚠️ *Unable to complete search right now.*\n\n"
                "We encountered an issue connecting to the search service or database. Please try again."
            ),
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Case 3: No results in requested area -> Prompt for confirmation before city-wide fallback!
    if status == "area_not_found":
        search_data = search_output.get("search_data", {})
        # Store pending fallback search data separately per user/chat
        context.user_data["pending_fallback"] = search_data

        label = get_friendly_search_label(search_data)
        area = search_data.get("area") or "this area"
        city = search_data.get("city") or "the city"

        prompt_text = (
            f"⚠️ No {label} found in *{area}*.\n\n"
            f"Would you like to see available {label} from other areas in *{city}*?"
        )
        await update.message.reply_text(
            text=prompt_text,
            reply_markup=get_area_fallback_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Case 4: No matching listings found
    if status == "no_results" or not results:
        no_results_message = (
            "😔 Sorry, I couldn't find any matching results.\n\n"
            "Try changing the city, category, or budget."
        )
        await update.message.reply_text(
            text=no_results_message,
            reply_markup=get_back_keyboard(),
        )
        return

    # Case 4: Results found - format and return
    results_text = format_ai_search_results(understanding, results, search_output)

    # Protect against Telegram message character limit (4096 chars)
    if len(results_text) > 4000:
        results_text = results_text[:3950] + "\n\n_(List truncated. Please refine your search.)_"

    try:
        await update.message.reply_text(
            text=results_text,
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        # Fallback to plain text if markdown formatting encounters unescaped characters
        await update.message.reply_text(
            text=results_text.replace("*", "").replace("_", ""),
            reply_markup=get_back_keyboard(),
        )


# 11. Command & Callback Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the UrbanEase welcome message with the main menu keyboard."""
    if update.message:
        await update.message.reply_text(
            text=WELCOME_TEXT,
            reply_markup=get_main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button clicks from the inline keyboard."""
    query = update.callback_query
    if not query:
        return

    # Acknowledge the callback query to clear Telegram's loading state
    await query.answer()

    data = query.data

    # -------------------------------------------------------------
    # Navigation: Return to Main Menu
    # -------------------------------------------------------------
    if data == "main_menu":
        context.user_data.clear()
        await query.edit_message_text(
            text=WELCOME_TEXT,
            reply_markup=get_main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    # -------------------------------------------------------------
    # Area Fallback Confirmation Handlers
    # -------------------------------------------------------------
    elif data == "show_other_areas":
        # Retrieve and clear the pending search state for this user
        pending_search = context.user_data.pop("pending_fallback", None)
        if not pending_search:
            await query.edit_message_text(
                text="⚠️ This search confirmation has expired or was already used. Please start a new search.",
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        fallback_output = search_without_area(pending_search)
        results = fallback_output.get("results", [])
        city = pending_search.get("city") or "the city"
        label = get_friendly_search_label(pending_search)

        if not results:
            await query.edit_message_text(
                text=f"😔 Sorry, no matching {label} were found in {city} either.\n\nTry searching for another category or budget.",
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        header = f"📍 *Available {label} from other areas in {city}:*\n\n"
        results_text = header + format_ai_search_results(pending_search, results)

        if len(results_text) > 4000:
            results_text = results_text[:3950] + "\n\n_(List truncated. Please refine your search.)_"

        try:
            await query.edit_message_text(
                text=results_text,
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await query.edit_message_text(
                text=results_text.replace("*", "").replace("_", ""),
                reply_markup=get_back_keyboard(),
            )

    elif data == "cancel_area_fallback":
        # Clear the pending search state for this user
        context.user_data.pop("pending_fallback", None)
        await query.edit_message_text(
            text="No problem! You can try searching for another area or service. 😊",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    # -------------------------------------------------------------
    # Natural Language Resumption (when city was prompted)
    # -------------------------------------------------------------
    elif data.startswith("nlcity_"):
        selected_city = data[len("nlcity_"):]
        pending = context.user_data.pop("pending_nl_search", None)

        if pending and "intent_data" in pending:
            results_message = execute_natural_language_search(
                intent_data=pending["intent_data"],
                city=selected_city,
                budget=pending.get("budget"),
            )
            await query.edit_message_text(
                text=results_message,
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await query.edit_message_text(
                text=WELCOME_TEXT,
                reply_markup=get_main_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )

    # -------------------------------------------------------------
    # Feature 1: Home Search Flow
    # -------------------------------------------------------------
    elif data == "find_home":
        cities = get_unique_cities()
        if cities is None:
            await query.edit_message_text(
                text="⚠️ *Unable to retrieve cities right now.*\n\nPlease try again in a few moments.",
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        elif not cities:
            await query.edit_message_text(
                text="🏠 *Find Your Home*\n\nNo property listings are currently available.\nPlease check back soon!",
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await query.edit_message_text(
                text="🏠 *Find Your Home*\n\nWhich city are you looking for?",
                reply_markup=get_cities_keyboard(cities),
                parse_mode=ParseMode.MARKDOWN,
            )

    elif data.startswith("city_"):
        selected_city = data[len("city_"):]
        context.user_data["selected_city"] = selected_city
        await show_property_types_screen(query, selected_city)

    elif data.startswith("type_"):
        selected_type = data[len("type_"):]
        selected_city = context.user_data.get("selected_city")

        if not selected_city:
            cities = get_unique_cities() or []
            await query.edit_message_text(
                text="🏠 *Find Your Home*\n\nPlease select your city first:",
                reply_markup=get_cities_keyboard(cities),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        context.user_data["selected_type"] = selected_type
        await show_budget_screen(query, selected_city, selected_type)

    elif data.startswith("bgt_"):
        budget_key = data[len("bgt_"):]
        selected_city = context.user_data.get("selected_city")
        selected_type = context.user_data.get("selected_type")

        if not selected_city or not selected_type:
            cities = get_unique_cities() or []
            await query.edit_message_text(
                text="🏠 *Find Your Home*\n\nPlease select your city first:",
                reply_markup=get_cities_keyboard(cities),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        budget_info = BUDGET_CONFIG.get(budget_key, BUDGET_CONFIG["none"])
        context.user_data["selected_budget_key"] = budget_key

        properties = search_properties(
            city=selected_city,
            property_type=selected_type,
            min_budget=budget_info["min"],
            max_budget=budget_info["max"],
        )

        if properties is None:
            response_text = (
                "⚠️ *Unable to retrieve properties right now.*\n\n"
                "We encountered an issue connecting to the database. Please try again."
            )
        else:
            response_text = format_search_results(
                properties=properties,
                city=selected_city,
                prop_type=selected_type,
                budget_label=budget_info["display"],
            )

        await query.edit_message_text(
            text=response_text,
            reply_markup=get_home_results_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "back_to_types":
        selected_city = context.user_data.get("selected_city")
        if not selected_city:
            cities = get_unique_cities() or []
            await query.edit_message_text(
                text="🏠 *Find Your Home*\n\nWhich city are you looking for?",
                reply_markup=get_cities_keyboard(cities),
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        await show_property_types_screen(query, selected_city)

    elif data == "back_to_budget":
        selected_city = context.user_data.get("selected_city")
        selected_type = context.user_data.get("selected_type")
        if not selected_city or not selected_type:
            cities = get_unique_cities() or []
            await query.edit_message_text(
                text="🏠 *Find Your Home*\n\nWhich city are you looking for?",
                reply_markup=get_cities_keyboard(cities),
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        await show_budget_screen(query, selected_city, selected_type)

    # -------------------------------------------------------------
    # Feature 2: Rental Appliances & Furniture Flow
    # -------------------------------------------------------------
    elif data == "rental_appliances":
        prompt_text = (
            "🛋️ *Rental Appliances & Furniture*\n\n"
            "What are you looking for?"
        )
        await query.edit_message_text(
            text=prompt_text,
            reply_markup=get_rental_categories_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("rentcat_"):
        selected_category = data[len("rentcat_"):]
        context.user_data["rental_category"] = selected_category
        await show_rental_cities_screen(query, selected_category)

    elif data.startswith("rentcity_"):
        selected_city = data[len("rentcity_"):]
        selected_category = context.user_data.get("rental_category")

        if not selected_category:
            prompt_text = (
                "🛋️ *Rental Appliances & Furniture*\n\n"
                "What are you looking for?"
            )
            await query.edit_message_text(
                text=prompt_text,
                reply_markup=get_rental_categories_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        context.user_data["rental_city"] = selected_city

        items = get_rental_items(
            category=selected_category,
            city=selected_city,
        )

        if items is None:
            response_text = (
                "⚠️ *Unable to retrieve rental items right now.*\n\n"
                "We encountered an issue connecting to the database. Please try again."
            )
        else:
            response_text = format_rental_items_results(
                items=items,
                category=selected_category,
                city=selected_city,
            )

        await query.edit_message_text(
            text=response_text,
            reply_markup=get_rental_results_keyboard(selected_category),
            parse_mode=ParseMode.MARKDOWN,
        )

    # -------------------------------------------------------------
    # Feature 3: Rental Vehicles Flow
    # -------------------------------------------------------------
    elif data == "rental_vehicles":
        vehicle_types = get_unique_vehicle_types()
        if vehicle_types is None:
            await query.edit_message_text(
                text="⚠️ *Unable to retrieve vehicle types right now.*\n\nPlease try again in a few moments.",
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        elif not vehicle_types:
            await query.edit_message_text(
                text="🚗 *Rental Vehicles*\n\nNo vehicles are currently listed.\nPlease check back soon!",
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            prompt_text = (
                "🚗 *Rental Vehicles*\n\n"
                "What type of vehicle are you looking for?"
            )
            await query.edit_message_text(
                text=prompt_text,
                reply_markup=get_vehicle_types_keyboard(vehicle_types),
                parse_mode=ParseMode.MARKDOWN,
            )

    elif data.startswith("vehtype_"):
        selected_type = data[len("vehtype_"):]
        context.user_data["vehicle_type"] = selected_type
        await show_vehicle_cities_screen(query, selected_type)

    elif data.startswith("vehcity_"):
        selected_city = data[len("vehcity_"):]
        selected_type = context.user_data.get("vehicle_type")

        if not selected_type:
            vehicle_types = get_unique_vehicle_types() or ["Bike", "Car"]
            prompt_text = (
                "🚗 *Rental Vehicles*\n\n"
                "What type of vehicle are you looking for?"
            )
            await query.edit_message_text(
                text=prompt_text,
                reply_markup=get_vehicle_types_keyboard(vehicle_types),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        context.user_data["vehicle_city"] = selected_city

        vehicles = get_vehicles(
            vehicle_type=selected_type,
            city=selected_city,
        )

        if vehicles is None:
            response_text = (
                "⚠️ *Unable to retrieve vehicles right now.*\n\n"
                "We encountered an issue connecting to the database. Please try again."
            )
        else:
            response_text = format_vehicles_results(
                vehicles=vehicles,
                vehicle_type=selected_type,
                city=selected_city,
            )

        await query.edit_message_text(
            text=response_text,
            reply_markup=get_vehicle_results_keyboard(selected_type),
            parse_mode=ParseMode.MARKDOWN,
        )

    # -------------------------------------------------------------
    # Feature 4: Find a Helper Flow (Service Providers)
    # -------------------------------------------------------------
    elif data == "find_helper":
        service_types = get_unique_service_types()
        if service_types is None:
            await query.edit_message_text(
                text="⚠️ *Unable to retrieve services right now.*\n\nPlease try again in a few moments.",
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        elif not service_types:
            await query.edit_message_text(
                text="🔧 *Find a Helper*\n\nNo service helpers are currently listed.\nPlease check back soon!",
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            prompt_text = (
                "🔧 *Find a Helper*\n\n"
                "What service do you need?"
            )
            await query.edit_message_text(
                text=prompt_text,
                reply_markup=get_service_types_keyboard(service_types),
                parse_mode=ParseMode.MARKDOWN,
            )

    elif data.startswith("srvtype_"):
        selected_service = data[len("srvtype_"):]
        context.user_data["helper_service"] = selected_service
        await show_service_cities_screen(query, selected_service)

    elif data.startswith("srvcity_"):
        selected_city = data[len("srvcity_"):]
        selected_service = context.user_data.get("helper_service")

        if not selected_service:
            service_types = get_unique_service_types() or ["Electrician", "Plumber", "Carpenter", "AC Repair", "Cleaner"]
            prompt_text = (
                "🔧 *Find a Helper*\n\n"
                "What service do you need?"
            )
            await query.edit_message_text(
                text=prompt_text,
                reply_markup=get_service_types_keyboard(service_types),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        context.user_data["helper_city"] = selected_city

        helpers = get_service_providers(
            service_type=selected_service,
            city=selected_city,
        )

        if helpers is None:
            response_text = (
                "⚠️ *Unable to retrieve helpers right now.*\n\n"
                "We encountered an issue connecting to the database. Please try again."
            )
        else:
            response_text = format_helpers_results(
                helpers=helpers,
                service_type=selected_service,
                city=selected_city,
            )

        await query.edit_message_text(
            text=response_text,
            reply_markup=get_service_results_keyboard(selected_service),
            parse_mode=ParseMode.MARKDOWN,
        )


# 12. Main Application Entrypoint
def main() -> None:
    """Builds the application, registers handlers, and starts polling."""
    app = ApplicationBuilder().token(TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start))

    # Register callback query handler for inline button clicks
    app.add_handler(CallbackQueryHandler(button_click))

    # Register message handler for natural language text queries
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_language_message))

    # Print terminal status message
    print("=" * 60)
    print("🚀 UrbanEase AI Telegram Assistant started successfully!")
    print("📡 Polling for messages... (Press Ctrl+C to stop)")
    print("=" * 60)

    # Start polling
    app.run_polling()


if __name__ == "__main__":
    main()
