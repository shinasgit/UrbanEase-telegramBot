import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

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

# 2. Read database credentials
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "urbanease")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# 3. Build SQLAlchemy Connection URL
DATABASE_URL = URL.create(
    drivername="postgresql+psycopg2",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT) if DB_PORT and DB_PORT.isdigit() else 5432,
    database=DB_NAME,
)

# 4. Create reusable database engine and session factory
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# 5. Database Queries: Properties (Home Search)
def get_unique_cities() -> list[str] | None:
    """
    Retrieves unique, non-null city names from the 'properties' table in PostgreSQL.
    Returns:
        list[str]: Sorted list of unique city names (e.g. ['Bangalore', 'Kochi']).
        None: If a database error occurs.
    """
    query = text("""
        SELECT DISTINCT city
        FROM properties
        WHERE city IS NOT NULL AND TRIM(city) != ''
        ORDER BY city ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query)
            return [row[0] for row in result]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving cities: {raw_error}", file=sys.stderr)
        return None


def get_unique_property_types() -> list[str] | None:
    """
    Retrieves unique property types dynamically from the 'properties' table in PostgreSQL.
    Returns:
        list[str]: Sorted list of unique property types (e.g. ['Flat', 'Hostel', 'PG']).
        None: If a database error occurs.
    """
    query = text("""
        SELECT DISTINCT property_type
        FROM properties
        WHERE property_type IS NOT NULL AND TRIM(property_type) != ''
        ORDER BY property_type ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query)
            types = [row[0] for row in result]
            return types if types else ["House", "Flat", "PG", "Hostel"]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving property types: {raw_error}", file=sys.stderr)
        return None


def search_properties(
    city: str,
    property_type: str | None = None,
    min_budget: float | None = None,
    max_budget: float | None = None,
) -> list[dict] | None:
    """
    Retrieves properties filtered by city, property_type, and budget range.
    Uses parameterized SQL queries safely to prevent SQL injection.
    """
    conditions = ["LOWER(city) = LOWER(:city)"]
    params: dict = {"city": city}

    if property_type and property_type.upper() != "ALL":
        conditions.append("LOWER(property_type) = LOWER(:property_type)")
        params["property_type"] = property_type

    if min_budget is not None:
        conditions.append("monthly_rent >= :min_budget")
        params["min_budget"] = min_budget

    if max_budget is not None:
        conditions.append("monthly_rent <= :max_budget")
        params["max_budget"] = max_budget

    where_clause = " AND ".join(conditions)
    query = text(f"""
        SELECT id, title, property_type, city, area, monthly_rent, bedrooms, description
        FROM properties
        WHERE {where_clause}
        ORDER BY monthly_rent ASC, id ASC
    """)

    try:
        with engine.connect() as connection:
            result = connection.execute(query, params)
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in search_properties: {raw_error}", file=sys.stderr)
        return None


def get_properties_by_city_and_type(city: str, property_type: str | None = None) -> list[dict] | None:
    """Convenience wrapper around search_properties without budget filtering."""
    return search_properties(city=city, property_type=property_type)


def get_properties_by_city(city: str) -> list[dict] | None:
    """Convenience wrapper around search_properties for city-only filtering."""
    return search_properties(city=city)


def get_all_properties() -> list[dict] | None:
    """Retrieves all property listings from the 'properties' table in PostgreSQL."""
    query = text("""
        SELECT id, title, property_type, city, area, monthly_rent, bedrooms, description
        FROM properties
        ORDER BY id ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query)
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving properties: {raw_error}", file=sys.stderr)
        return None


# 6. Database Queries: Rental Items (Appliances & Furniture)
def get_rental_cities(category: str) -> list[str] | None:
    """
    Retrieves unique cities that currently have available rental items for a given category.
    Only returns cities where available = TRUE.
    """
    query = text("""
        SELECT DISTINCT city
        FROM rental_items
        WHERE LOWER(category) = LOWER(:category)
          AND available = TRUE
          AND city IS NOT NULL
          AND TRIM(city) != ''
        ORDER BY city ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, {"category": category})
            return [row[0] for row in result]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving rental cities for {category}: {raw_error}", file=sys.stderr)
        return None


def get_rental_items(category: str, city: str) -> list[dict] | None:
    """
    Retrieves all available rental items for a given category and city.
    Uses parameterized queries and filters by available = TRUE.
    """
    query = text("""
        SELECT id, name, category, city, area, monthly_rent, description, available
        FROM rental_items
        WHERE LOWER(category) = LOWER(:category)
          AND LOWER(city) = LOWER(:city)
          AND available = TRUE
        ORDER BY monthly_rent ASC, id ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, {"category": category, "city": city})
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving rental items for {category} in {city}: {raw_error}", file=sys.stderr)
        return None


def search_rental_items_nl(
    city: str,
    category: str | None = None,
    item_keyword: str | None = None,
) -> list[dict] | None:
    """
    Searches rental items using city, category, and optional name keyword matching.
    Used for Natural Language search.
    """
    conditions = ["LOWER(city) = LOWER(:city)", "available = TRUE"]
    params: dict = {"city": city}

    if category:
        conditions.append("LOWER(category) = LOWER(:category)")
        params["category"] = category

    if item_keyword and item_keyword.lower() not in ["appliance", "appliances", "furniture", "rental"]:
        conditions.append("(LOWER(name) LIKE LOWER(:item_kw) OR LOWER(description) LIKE LOWER(:item_kw))")
        params["item_kw"] = f"%{item_keyword}%"

    where_clause = " AND ".join(conditions)
    query = text(f"""
        SELECT id, name, category, city, area, monthly_rent, description, available
        FROM rental_items
        WHERE {where_clause}
        ORDER BY monthly_rent ASC, id ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, params)
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in search_rental_items_nl: {raw_error}", file=sys.stderr)
        return None


# 7. Database Queries: Rental Vehicles (Bikes & Cars)
def get_unique_vehicle_types() -> list[str] | None:
    """
    Retrieves unique vehicle types dynamically from the 'vehicles' table in PostgreSQL.
    Only returns types where available = TRUE.
    Returns:
        list[str]: Sorted list of vehicle types (e.g. ['Bike', 'Car']).
        None: If a database error occurs.
    """
    query = text("""
        SELECT DISTINCT vehicle_type
        FROM vehicles
        WHERE available = TRUE
          AND vehicle_type IS NOT NULL
          AND TRIM(vehicle_type) != ''
        ORDER BY vehicle_type ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query)
            types = [row[0] for row in result]
            return types if types else ["Bike", "Car"]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving vehicle types: {raw_error}", file=sys.stderr)
        return None


def get_vehicle_cities(vehicle_type: str) -> list[str] | None:
    """
    Retrieves unique cities that currently have available vehicles for a given vehicle type.
    Only returns cities where available = TRUE.
    """
    query = text("""
        SELECT DISTINCT city
        FROM vehicles
        WHERE LOWER(vehicle_type) = LOWER(:vehicle_type)
          AND available = TRUE
          AND city IS NOT NULL
          AND TRIM(city) != ''
        ORDER BY city ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, {"vehicle_type": vehicle_type})
            return [row[0] for row in result]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving vehicle cities for {vehicle_type}: {raw_error}", file=sys.stderr)
        return None


def get_vehicles(vehicle_type: str, city: str) -> list[dict] | None:
    """
    Retrieves all available vehicles for a given vehicle_type and city.
    Uses parameterized queries and filters by available = TRUE.
    """
    query = text("""
        SELECT id, name, vehicle_type, brand, city, area, daily_rent, description, available
        FROM vehicles
        WHERE LOWER(vehicle_type) = LOWER(:vehicle_type)
          AND LOWER(city) = LOWER(:city)
          AND available = TRUE
        ORDER BY daily_rent ASC, id ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, {"vehicle_type": vehicle_type, "city": city})
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving vehicles for {vehicle_type} in {city}: {raw_error}", file=sys.stderr)
        return None


def search_vehicles_nl(
    city: str,
    vehicle_type: str | None = None,
    vehicle_keyword: str | None = None,
) -> list[dict] | None:
    """
    Searches vehicles using city, vehicle_type, and optional name keyword matching.
    Used for Natural Language search.
    """
    conditions = ["LOWER(city) = LOWER(:city)", "available = TRUE"]
    params: dict = {"city": city}

    if vehicle_type and vehicle_type.upper() != "ALL":
        conditions.append("LOWER(vehicle_type) = LOWER(:vtype)")
        params["vtype"] = vehicle_type

    if vehicle_keyword and vehicle_keyword.lower() not in ["bike", "car", "vehicle"]:
        conditions.append("(LOWER(name) LIKE LOWER(:vkw) OR LOWER(brand) LIKE LOWER(:vkw))")
        params["vkw"] = f"%{vehicle_keyword}%"

    where_clause = " AND ".join(conditions)
    query = text(f"""
        SELECT id, name, vehicle_type, brand, city, area, daily_rent, description, available
        FROM vehicles
        WHERE {where_clause}
        ORDER BY daily_rent ASC, id ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, params)
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in search_vehicles_nl: {raw_error}", file=sys.stderr)
        return None


# 8. Database Queries: Service Providers (Find a Helper)
def get_unique_service_types() -> list[str] | None:
    """
    Retrieves unique service types dynamically from the 'service_providers' table in PostgreSQL.
    Only returns types where available = TRUE.
    Returns:
        list[str]: Sorted list of service types (e.g. ['Electrician', 'Plumber', ...]).
        None: If a database error occurs.
    """
    query = text("""
        SELECT DISTINCT service_type
        FROM service_providers
        WHERE available = TRUE
          AND service_type IS NOT NULL
          AND TRIM(service_type) != ''
        ORDER BY service_type ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query)
            types = [row[0] for row in result]
            return types if types else ["Electrician", "Plumber", "Carpenter", "AC Repair", "Cleaner"]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving service types: {raw_error}", file=sys.stderr)
        return None


def get_service_cities(service_type: str) -> list[str] | None:
    """
    Retrieves unique cities that currently have available helpers for a given service_type.
    Only returns cities where available = TRUE.
    """
    query = text("""
        SELECT DISTINCT city
        FROM service_providers
        WHERE LOWER(service_type) = LOWER(:service_type)
          AND available = TRUE
          AND city IS NOT NULL
          AND TRIM(city) != ''
        ORDER BY city ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, {"service_type": service_type})
            return [row[0] for row in result]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving service cities for {service_type}: {raw_error}", file=sys.stderr)
        return None


def get_service_providers(service_type: str, city: str) -> list[dict] | None:
    """
    Retrieves all available service providers for a given service_type and city.
    Uses parameterized queries and filters by available = TRUE.
    """
    query = text("""
        SELECT id, name, service_type, city, area, phone, description, available
        FROM service_providers
        WHERE LOWER(service_type) = LOWER(:service_type)
          AND LOWER(city) = LOWER(:city)
          AND available = TRUE
        ORDER BY id ASC
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, {"service_type": service_type, "city": city})
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error while retrieving helpers for {service_type} in {city}: {raw_error}", file=sys.stderr)
        return None


# 9. Database Connection Test Function
def test_connection() -> bool:
    """
    Tests whether Python can successfully connect to the PostgreSQL database.
    Executes a simple 'SELECT 1' query and prints the status.
    Guarantees the database password is never exposed in error logs.
    """
    print(f"Connecting to PostgreSQL database '{DB_NAME}' at {DB_HOST}:{DB_PORT} as user '{DB_USER}'...")
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            if result.scalar() == 1:
                print("✅ Successfully connected to the 'urbanease' PostgreSQL database!")
                return True
            return False

    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")

        print("❌ Database Connection Failed!")
        print("--------------------------------------------------")
        print(f"Host:     {DB_HOST}:{DB_PORT}")
        print(f"Database: {DB_NAME}")
        print(f"User:     {DB_USER}")
        print(f"Details:  {raw_error}")
        print("--------------------------------------------------")
        print("💡 Tip: Please check that PostgreSQL is running and verify DB_PASSWORD in your .env file.")
        return False

    except Exception as exc:
        print(f"❌ Unexpected error while connecting: {exc}")
        return False


if __name__ == "__main__":
    test_connection()
