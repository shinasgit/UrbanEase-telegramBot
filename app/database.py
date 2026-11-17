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
    city: str | None = None,
    property_type: str | None = None,
    min_budget: float | None = None,
    max_budget: float | None = None,
    area: str | None = None,
) -> list[dict] | None:
    """
    Retrieves properties filtered by city, property_type, budget range, and optional area.
    If a filter field is None, that filter is omitted.
    Uses parameterized SQL queries safely to prevent SQL injection.
    """
    conditions = []
    params: dict = {}

    if city:
        conditions.append("LOWER(city) = LOWER(:city)")
        params["city"] = city

    if property_type and property_type.upper() != "ALL":
        conditions.append("LOWER(property_type) = LOWER(:property_type)")
        params["property_type"] = property_type

    if min_budget is not None:
        conditions.append("monthly_rent >= :min_budget")
        params["min_budget"] = min_budget

    if max_budget is not None:
        conditions.append("monthly_rent <= :max_budget")
        params["max_budget"] = max_budget

    if area:
        conditions.append("LOWER(area) LIKE LOWER(:area_pattern)")
        params["area_pattern"] = f"%{area.strip()}%"
        params["exact_area"] = area.strip()
        order_clause = "CASE WHEN LOWER(area) = LOWER(:exact_area) THEN 0 ELSE 1 END ASC, monthly_rent ASC, id ASC"
    else:
        order_clause = "monthly_rent ASC, id ASC"

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    query = text(f"""
        SELECT id, title, property_type, city, area, monthly_rent, bedrooms, description
        FROM properties
        WHERE {where_clause}
        ORDER BY {order_clause}
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
    city: str | None = None,
    category: str | None = None,
    item_keyword: str | None = None,
    area: str | None = None,
) -> list[dict] | None:
    """
    Searches rental items using city, category, optional name keyword, and optional area matching.
    If a filter field is None, that filter is omitted.
    Used for Natural Language search.
    """
    conditions = ["available = TRUE"]
    params: dict = {}

    if city:
        conditions.append("LOWER(city) = LOWER(:city)")
        params["city"] = city

    if category:
        conditions.append("LOWER(category) = LOWER(:category)")
        params["category"] = category

    if item_keyword and item_keyword.lower() not in ["appliance", "appliances", "furniture", "rental"]:
        conditions.append("(LOWER(name) LIKE LOWER(:item_kw) OR LOWER(description) LIKE LOWER(:item_kw))")
        params["item_kw"] = f"%{item_keyword}%"

    if area:
        conditions.append("LOWER(area) LIKE LOWER(:area_pattern)")
        params["area_pattern"] = f"%{area.strip()}%"
        params["exact_area"] = area.strip()
        order_clause = "CASE WHEN LOWER(area) = LOWER(:exact_area) THEN 0 ELSE 1 END ASC, monthly_rent ASC, id ASC"
    else:
        order_clause = "monthly_rent ASC, id ASC"

    where_clause = " AND ".join(conditions)
    query = text(f"""
        SELECT id, name, category, city, area, monthly_rent, description, available
        FROM rental_items
        WHERE {where_clause}
        ORDER BY {order_clause}
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
    city: str | None = None,
    vehicle_type: str | None = None,
    vehicle_keyword: str | None = None,
    area: str | None = None,
) -> list[dict] | None:
    """
    Searches vehicles using city, vehicle_type, optional name keyword, and optional area matching.
    If a filter field is None, that filter is omitted.
    Used for Natural Language search.
    """
    conditions = ["available = TRUE"]
    params: dict = {}

    if city:
        conditions.append("LOWER(city) = LOWER(:city)")
        params["city"] = city

    if vehicle_type and vehicle_type.upper() != "ALL":
        conditions.append("LOWER(vehicle_type) = LOWER(:vtype)")
        params["vtype"] = vehicle_type

    if vehicle_keyword and vehicle_keyword.lower() not in ["bike", "car", "vehicle"]:
        conditions.append("(LOWER(name) LIKE LOWER(:vkw) OR LOWER(brand) LIKE LOWER(:vkw))")
        params["vkw"] = f"%{vehicle_keyword}%"

    if area:
        conditions.append("LOWER(area) LIKE LOWER(:area_pattern)")
        params["area_pattern"] = f"%{area.strip()}%"
        params["exact_area"] = area.strip()
        order_clause = "CASE WHEN LOWER(area) = LOWER(:exact_area) THEN 0 ELSE 1 END ASC, daily_rent ASC, id ASC"
    else:
        order_clause = "daily_rent ASC, id ASC"

    where_clause = " AND ".join(conditions)
    query = text(f"""
        SELECT id, name, vehicle_type, brand, city, area, daily_rent, description, available
        FROM vehicles
        WHERE {where_clause}
        ORDER BY {order_clause}
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


def search_service_providers(
    service_type: str | None = None,
    city: str | None = None,
    area: str | None = None,
) -> list[dict] | None:
    """
    Retrieves available service providers filtered by service_type, city, and/or area.
    If a parameter is None, that filter is omitted.
    Uses parameterized queries and filters by available = TRUE.
    """
    conditions = ["available = TRUE"]
    params: dict = {}

    if service_type:
        conditions.append("LOWER(service_type) = LOWER(:service_type)")
        params["service_type"] = service_type

    if city:
        conditions.append("LOWER(city) = LOWER(:city)")
        params["city"] = city

    if area:
        conditions.append("(LOWER(area) LIKE LOWER(:area_pattern) OR LOWER(description) LIKE LOWER(:area_pattern))")
        params["area_pattern"] = f"%{area.strip()}%"
        params["exact_area"] = area.strip()
        order_clause = "CASE WHEN LOWER(area) = LOWER(:exact_area) THEN 0 WHEN LOWER(area) LIKE LOWER(:area_pattern) THEN 1 ELSE 2 END ASC, id ASC"
    else:
        order_clause = "id ASC"

    where_clause = " AND ".join(conditions)
    query = text(f"""
        SELECT id, name, service_type, city, area, phone, description, available,
               source, source_id, latitude, longitude, website, last_updated
        FROM service_providers
        WHERE {where_clause}
        ORDER BY {order_clause}
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, params)
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in search_service_providers: {raw_error}", file=sys.stderr)
        return None


def get_service_providers(service_type: str, city: str) -> list[dict] | None:
    """
    Retrieves all available service providers for a given service_type and city.
    Uses parameterized queries and filters by available = TRUE.
    """
    return search_service_providers(service_type=service_type, city=city)


def ensure_service_providers_schema() -> bool:
    """
    Ensures that the 'service_providers' table contains columns needed for
    external data sources (e.g. OpenStreetMap), including source, source_id,
    latitude, longitude, website, and last_updated.
    Also ensures a unique partial index on source_id to prevent duplicate entries.
    Safe and idempotent.
    """
    statements = [
        "ALTER TABLE service_providers ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'Manual'",
        "ALTER TABLE service_providers ADD COLUMN IF NOT EXISTS source_id VARCHAR(100)",
        "ALTER TABLE service_providers ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION",
        "ALTER TABLE service_providers ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION",
        "ALTER TABLE service_providers ADD COLUMN IF NOT EXISTS website TEXT",
        "ALTER TABLE service_providers ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_service_providers_source_id ON service_providers (source_id) WHERE source_id IS NOT NULL",
        # Sync the serial sequence to prevent primary-key conflicts when inserting new rows
        # after rows were inserted manually without consuming the sequence.
        "SELECT setval(pg_get_serial_sequence('service_providers', 'id'), (SELECT COALESCE(MAX(id), 1) FROM service_providers))",
    ]
    try:
        with engine.begin() as connection:
            for stmt in statements:
                connection.execute(text(stmt))
        return True
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in ensure_service_providers_schema: {raw_error}", file=sys.stderr)
        return False


def upsert_service_provider(provider_data: dict) -> tuple[str, int | None]:
    """
    Inserts a new service provider or updates an existing one based on source_id.
    
    Returns:
        tuple[str, int | None]: ("inserted" | "updated" | "skipped" | "error", record_id)
    """
    source_id = provider_data.get("source_id")
    if not source_id:
        return ("skipped", None)

    select_sql = text("SELECT id FROM service_providers WHERE source_id = :source_id LIMIT 1")

    update_sql = text("""
        UPDATE service_providers
        SET name = :name,
            service_type = :service_type,
            city = :city,
            area = COALESCE(:area, area),
            phone = COALESCE(:phone, phone),
            description = COALESCE(:description, description),
            available = :available,
            source = :source,
            latitude = COALESCE(:latitude, latitude),
            longitude = COALESCE(:longitude, longitude),
            website = COALESCE(:website, website),
            last_updated = CURRENT_TIMESTAMP
        WHERE source_id = :source_id
        RETURNING id
    """)

    insert_sql = text("""
        INSERT INTO service_providers (
            name, service_type, city, area, phone, description,
            available, source, source_id, latitude, longitude, website,
            created_at, last_updated
        ) VALUES (
            :name, :service_type, :city, :area, :phone, :description,
            :available, :source, :source_id, :latitude, :longitude, :website,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
    """)

    params = {
        "name": provider_data.get("name"),
        "service_type": provider_data.get("service_type"),
        "city": provider_data.get("city"),
        "area": provider_data.get("area"),
        "phone": provider_data.get("phone"),
        "description": provider_data.get("description"),
        "available": provider_data.get("available", True),
        "source": provider_data.get("source", "OpenStreetMap"),
        "source_id": source_id,
        "latitude": provider_data.get("latitude"),
        "longitude": provider_data.get("longitude"),
        "website": provider_data.get("website"),
    }

    try:
        with engine.begin() as connection:
            existing = connection.execute(select_sql, {"source_id": source_id}).first()
            if existing:
                res = connection.execute(update_sql, params)
                updated_id = res.scalar()
                return ("updated", updated_id)
            else:
                res = connection.execute(insert_sql, params)
                new_id = res.scalar()
                return ("inserted", new_id)
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in upsert_service_provider: {raw_error}", file=sys.stderr)
        return ("error", None)


# 9. Database Queries & Management: Vehicle Rental Providers (OpenStreetMap)
def ensure_vehicle_rental_providers_schema() -> bool:
    """
    Ensures that the 'vehicle_rental_providers' table exists with appropriate columns
    and indexes for real-world vehicle rental businesses (Bike/Car/Both).
    Idempotent and safe.
    """
    statements = [
        """
        CREATE TABLE IF NOT EXISTS vehicle_rental_providers (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            vehicle_type VARCHAR(50) NOT NULL,
            city VARCHAR(100) NOT NULL,
            area VARCHAR(100),
            phone VARCHAR(100),
            website TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            source VARCHAR(50) DEFAULT 'OpenStreetMap',
            source_id VARCHAR(100),
            description TEXT,
            available BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_vehicle_rental_providers_source_id
        ON vehicle_rental_providers (source_id)
        WHERE source_id IS NOT NULL
        """,
        # Synchronize serial sequence to prevent primary key collision
        "SELECT setval(pg_get_serial_sequence('vehicle_rental_providers', 'id'), (SELECT COALESCE(MAX(id), 1) FROM vehicle_rental_providers))",
    ]
    try:
        with engine.begin() as connection:
            for stmt in statements:
                connection.execute(text(stmt))
        return True
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in ensure_vehicle_rental_providers_schema: {raw_error}", file=sys.stderr)
        return False


def upsert_vehicle_rental_provider(provider_data: dict) -> tuple[str, int | None]:
    """
    Inserts a new vehicle rental provider or updates an existing one based on source_id.

    Returns:
        tuple[str, int | None]: ("inserted" | "updated" | "skipped" | "error", record_id)
    """
    source_id = provider_data.get("source_id")
    if not source_id:
        return ("skipped", None)

    select_sql = text("SELECT id FROM vehicle_rental_providers WHERE source_id = :source_id LIMIT 1")

    update_sql = text("""
        UPDATE vehicle_rental_providers
        SET name = :name,
            vehicle_type = :vehicle_type,
            city = :city,
            area = COALESCE(:area, area),
            phone = COALESCE(:phone, phone),
            description = COALESCE(:description, description),
            available = :available,
            source = :source,
            latitude = COALESCE(:latitude, latitude),
            longitude = COALESCE(:longitude, longitude),
            website = COALESCE(:website, website),
            last_updated = CURRENT_TIMESTAMP
        WHERE source_id = :source_id
        RETURNING id
    """)

    insert_sql = text("""
        INSERT INTO vehicle_rental_providers (
            name, vehicle_type, city, area, phone, description,
            available, source, source_id, latitude, longitude, website,
            created_at, last_updated
        ) VALUES (
            :name, :vehicle_type, :city, :area, :phone, :description,
            :available, :source, :source_id, :latitude, :longitude, :website,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
    """)

    params = {
        "name": provider_data.get("name"),
        "vehicle_type": provider_data.get("vehicle_type"),
        "city": provider_data.get("city"),
        "area": provider_data.get("area"),
        "phone": provider_data.get("phone"),
        "description": provider_data.get("description"),
        "available": provider_data.get("available", True),
        "source": provider_data.get("source", "OpenStreetMap"),
        "source_id": source_id,
        "latitude": provider_data.get("latitude"),
        "longitude": provider_data.get("longitude"),
        "website": provider_data.get("website"),
    }

    try:
        with engine.begin() as connection:
            existing = connection.execute(select_sql, {"source_id": source_id}).first()
            if existing:
                res = connection.execute(update_sql, params)
                updated_id = res.scalar()
                return ("updated", updated_id)
            else:
                res = connection.execute(insert_sql, params)
                new_id = res.scalar()
                return ("inserted", new_id)
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in upsert_vehicle_rental_provider: {raw_error}", file=sys.stderr)
        return ("error", None)


def search_vehicle_rental_providers(
    city: str | None = None,
    vehicle_type: str | None = None,
    keyword: str | None = None,
    area: str | None = None,
) -> list[dict] | None:
    """
    Searches 'vehicle_rental_providers' filtered by city, vehicle_type (Bike, Car, Both),
    optional keyword, and optional area.
    If vehicle_type is 'Bike', matches vehicle_type IN ('Bike', 'Both').
    If vehicle_type is 'Car', matches vehicle_type IN ('Car', 'Both').
    Uses parameterized SQL queries safely to prevent SQL injection.
    """
    conditions = ["available = TRUE"]
    params: dict = {}

    if city:
        conditions.append("LOWER(city) = LOWER(:city)")
        params["city"] = city

    if vehicle_type and vehicle_type.upper() != "ALL":
        conditions.append("(LOWER(vehicle_type) = LOWER(:vtype) OR LOWER(vehicle_type) = 'both')")
        params["vtype"] = vehicle_type

    if keyword and keyword.lower() not in ["bike", "car", "vehicle", "rental"]:
        conditions.append("(LOWER(name) LIKE LOWER(:kw) OR LOWER(description) LIKE LOWER(:kw) OR LOWER(area) LIKE LOWER(:kw))")
        params["kw"] = f"%{keyword}%"

    if area:
        conditions.append("(LOWER(area) LIKE LOWER(:area_pattern) OR LOWER(description) LIKE LOWER(:area_pattern))")
        params["area_pattern"] = f"%{area.strip()}%"
        params["exact_area"] = area.strip()
        order_clause = "CASE WHEN LOWER(area) = LOWER(:exact_area) THEN 0 WHEN LOWER(area) LIKE LOWER(:area_pattern) THEN 1 ELSE 2 END ASC, id ASC"
    else:
        order_clause = "id ASC"

    where_clause = " AND ".join(conditions)
    query = text(f"""
        SELECT id, name, vehicle_type, city, area, phone, website,
               latitude, longitude, source, source_id, description, available, last_updated
        FROM vehicle_rental_providers
        WHERE {where_clause}
        ORDER BY {order_clause}
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, params)
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in search_vehicle_rental_providers: {raw_error}", file=sys.stderr)
        return None


# 9. Database Functions: Rental Item Providers (Appliances & Furniture Businesses)
def ensure_rental_item_providers_schema() -> bool:
    """
    Creates the 'rental_item_providers' table and its partial unique index
    if they do not already exist, and synchronizes the primary key sequence.
    """
    statements = [
        """
        CREATE TABLE IF NOT EXISTS rental_item_providers (
            id SERIAL PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            category VARCHAR(50) NOT NULL,
            city VARCHAR(50) NOT NULL,
            area VARCHAR(100),
            phone VARCHAR(50),
            website VARCHAR(200),
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            source VARCHAR(50) DEFAULT 'OpenStreetMap',
            source_id VARCHAR(100),
            description TEXT,
            available BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_rental_item_providers_source_id
        ON rental_item_providers (source_id)
        WHERE source_id IS NOT NULL
        """,
        # Synchronize serial sequence to prevent primary key collision
        "SELECT setval(pg_get_serial_sequence('rental_item_providers', 'id'), (SELECT COALESCE(MAX(id), 1) FROM rental_item_providers))",
    ]
    try:
        with engine.begin() as connection:
            for stmt in statements:
                connection.execute(text(stmt))
        return True
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in ensure_rental_item_providers_schema: {raw_error}", file=sys.stderr)
        return False


def upsert_rental_item_provider(provider_data: dict) -> tuple[str, int | None]:
    """
    Inserts a new rental item provider or updates an existing one based on source_id.

    Returns:
        tuple[str, int | None]: ("inserted" | "updated" | "skipped" | "error", record_id)
    """
    source_id = provider_data.get("source_id")
    if not source_id:
        return ("skipped", None)

    select_sql = text("SELECT id FROM rental_item_providers WHERE source_id = :source_id LIMIT 1")

    update_sql = text("""
        UPDATE rental_item_providers
        SET name = :name,
            category = :category,
            city = :city,
            area = COALESCE(:area, area),
            phone = COALESCE(:phone, phone),
            description = COALESCE(:description, description),
            available = :available,
            source = :source,
            latitude = COALESCE(:latitude, latitude),
            longitude = COALESCE(:longitude, longitude),
            website = COALESCE(:website, website),
            last_updated = CURRENT_TIMESTAMP
        WHERE source_id = :source_id
        RETURNING id
    """)

    insert_sql = text("""
        INSERT INTO rental_item_providers (
            name, category, city, area, phone, description,
            available, source, source_id, latitude, longitude, website,
            created_at, last_updated
        ) VALUES (
            :name, :category, :city, :area, :phone, :description,
            :available, :source, :source_id, :latitude, :longitude, :website,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
    """)

    params = {
        "name": provider_data.get("name"),
        "category": provider_data.get("category"),
        "city": provider_data.get("city"),
        "area": provider_data.get("area"),
        "phone": provider_data.get("phone"),
        "description": provider_data.get("description"),
        "available": provider_data.get("available", True),
        "source": provider_data.get("source", "OpenStreetMap"),
        "source_id": source_id,
        "latitude": provider_data.get("latitude"),
        "longitude": provider_data.get("longitude"),
        "website": provider_data.get("website"),
    }

    try:
        with engine.begin() as connection:
            existing = connection.execute(select_sql, {"source_id": source_id}).first()
            if existing:
                res = connection.execute(update_sql, params)
                updated_id = res.scalar()
                return ("updated", updated_id)
            else:
                res = connection.execute(insert_sql, params)
                new_id = res.scalar()
                return ("inserted", new_id)
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in upsert_rental_item_provider: {raw_error}", file=sys.stderr)
        return ("error", None)


def search_rental_item_providers(
    city: str | None = None,
    category: str | None = None,
    keyword: str | None = None,
    area: str | None = None,
) -> list[dict] | None:
    """
    Searches 'rental_item_providers' filtered by city, category (Appliance, Furniture, Both),
    optional keyword, and optional area.
    If category is 'Appliance', matches category IN ('Appliance', 'Both').
    If category is 'Furniture', matches category IN ('Furniture', 'Both').
    Uses parameterized SQL queries safely to prevent SQL injection.
    """
    conditions = ["available = TRUE"]
    params: dict = {}

    if city:
        conditions.append("LOWER(city) = LOWER(:city)")
        params["city"] = city

    if category and category.upper() != "ALL":
        conditions.append("(LOWER(category) = LOWER(:category) OR LOWER(category) = 'both')")
        params["category"] = category

    if keyword and keyword.lower() not in ["rental", "rent", "furniture", "appliance", "item"]:
        conditions.append("(LOWER(name) LIKE LOWER(:kw) OR LOWER(description) LIKE LOWER(:kw) OR LOWER(area) LIKE LOWER(:kw))")
        params["kw"] = f"%{keyword}%"

    if area:
        conditions.append("(LOWER(area) LIKE LOWER(:area_pattern) OR LOWER(description) LIKE LOWER(:area_pattern))")
        params["area_pattern"] = f"%{area.strip()}%"
        params["exact_area"] = area.strip()
        order_clause = "CASE WHEN LOWER(area) = LOWER(:exact_area) THEN 0 WHEN LOWER(area) LIKE LOWER(:area_pattern) THEN 1 ELSE 2 END ASC, id ASC"
    else:
        order_clause = "id ASC"

    where_clause = " AND ".join(conditions)
    query = text(f"""
        SELECT id, name, category, city, area, phone, website,
               latitude, longitude, source, source_id, description, available, last_updated
        FROM rental_item_providers
        WHERE {where_clause}
        ORDER BY {order_clause}
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, params)
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in search_rental_item_providers: {raw_error}", file=sys.stderr)
        return None


# 10. Database Functions: Property Places (Hostels, PGs, Apartments, Accommodations)
def ensure_property_places_schema() -> bool:
    """
    Creates the 'property_places' table and its partial unique index
    if they do not already exist, and synchronizes the primary key sequence.
    """
    statements = [
        """
        CREATE TABLE IF NOT EXISTS property_places (
            id SERIAL PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            property_type VARCHAR(50) NOT NULL,
            city VARCHAR(50) NOT NULL,
            area VARCHAR(100),
            address TEXT,
            phone VARCHAR(50),
            website VARCHAR(200),
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            source VARCHAR(50) DEFAULT 'OpenStreetMap',
            source_id VARCHAR(100),
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_property_places_source_id
        ON property_places (source_id)
        WHERE source_id IS NOT NULL
        """,
        # Synchronize serial sequence to prevent primary key collision
        "SELECT setval(pg_get_serial_sequence('property_places', 'id'), (SELECT COALESCE(MAX(id), 1) FROM property_places))",
    ]
    try:
        with engine.begin() as connection:
            for stmt in statements:
                connection.execute(text(stmt))
        return True
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in ensure_property_places_schema: {raw_error}", file=sys.stderr)
        return False


def upsert_property_place(place_data: dict) -> tuple[str, int | None]:
    """
    Inserts a new property place or updates an existing one based on source_id.

    Returns:
        tuple[str, int | None]: ("inserted" | "updated" | "skipped" | "error", record_id)
    """
    source_id = place_data.get("source_id")
    if not source_id:
        return ("skipped", None)

    select_sql = text("SELECT id FROM property_places WHERE source_id = :source_id LIMIT 1")

    update_sql = text("""
        UPDATE property_places
        SET name = :name,
            property_type = :property_type,
            city = :city,
            area = COALESCE(:area, area),
            address = COALESCE(:address, address),
            phone = COALESCE(:phone, phone),
            description = COALESCE(:description, description),
            source = :source,
            latitude = COALESCE(:latitude, latitude),
            longitude = COALESCE(:longitude, longitude),
            website = COALESCE(:website, website),
            last_updated = CURRENT_TIMESTAMP
        WHERE source_id = :source_id
        RETURNING id
    """)

    insert_sql = text("""
        INSERT INTO property_places (
            name, property_type, city, area, address, phone, description,
            source, source_id, latitude, longitude, website,
            created_at, last_updated
        ) VALUES (
            :name, :property_type, :city, :area, :address, :phone, :description,
            :source, :source_id, :latitude, :longitude, :website,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
    """)

    params = {
        "name": place_data.get("name"),
        "property_type": place_data.get("property_type"),
        "city": place_data.get("city"),
        "area": place_data.get("area"),
        "address": place_data.get("address"),
        "phone": place_data.get("phone"),
        "description": place_data.get("description"),
        "source": place_data.get("source", "OpenStreetMap"),
        "source_id": source_id,
        "latitude": place_data.get("latitude"),
        "longitude": place_data.get("longitude"),
        "website": place_data.get("website"),
    }

    try:
        with engine.begin() as connection:
            existing = connection.execute(select_sql, {"source_id": source_id}).first()
            if existing:
                res = connection.execute(update_sql, params)
                updated_id = res.scalar()
                return ("updated", updated_id)
            else:
                res = connection.execute(insert_sql, params)
                new_id = res.scalar()
                return ("inserted", new_id)
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in upsert_property_place: {raw_error}", file=sys.stderr)
        return ("error", None)


def search_property_places(
    city: str | None = None,
    property_type: str | None = None,
    keyword: str | None = None,
    area: str | None = None,
) -> list[dict] | None:
    """
    Searches 'property_places' filtered by city, property_type (House, Flat, PG, Hostel),
    optional keyword, and optional area.
    Uses parameterized SQL queries safely to prevent SQL injection.
    """
    conditions = []
    params: dict = {}

    if city:
        conditions.append("LOWER(city) = LOWER(:city)")
        params["city"] = city

    if property_type and property_type.upper() != "ALL":
        conditions.append("LOWER(property_type) = LOWER(:property_type)")
        params["property_type"] = property_type

    if keyword and keyword.lower() not in ["property", "place", "accommodation", "room"]:
        conditions.append("(LOWER(name) LIKE LOWER(:kw) OR LOWER(description) LIKE LOWER(:kw) OR LOWER(area) LIKE LOWER(:kw) OR LOWER(address) LIKE LOWER(:kw))")
        params["kw"] = f"%{keyword}%"

    if area:
        conditions.append("(LOWER(area) LIKE LOWER(:area_pattern) OR LOWER(address) LIKE LOWER(:area_pattern) OR LOWER(description) LIKE LOWER(:area_pattern))")
        params["area_pattern"] = f"%{area.strip()}%"
        params["exact_area"] = area.strip()
        order_clause = "CASE WHEN LOWER(area) = LOWER(:exact_area) THEN 0 WHEN LOWER(area) LIKE LOWER(:area_pattern) THEN 1 ELSE 2 END ASC, id ASC"
    else:
        order_clause = "id ASC"

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    query = text(f"""
        SELECT id, name, property_type, city, area, address, phone, website,
               latitude, longitude, source, source_id, description, last_updated
        FROM property_places
        WHERE {where_clause}
        ORDER BY {order_clause}
    """)
    try:
        with engine.connect() as connection:
            result = connection.execute(query, params)
            return [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        raw_error = str(exc)
        if DB_PASSWORD and DB_PASSWORD in raw_error:
            raw_error = raw_error.replace(DB_PASSWORD, "******")
        print(f"❌ Database error in search_property_places: {raw_error}", file=sys.stderr)
        return None


# 11. Database Connection Test Function
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
