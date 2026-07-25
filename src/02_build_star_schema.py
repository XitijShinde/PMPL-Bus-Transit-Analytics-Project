import duckdb
import pandas as pd
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "pmpml.duckdb"


def time_to_seconds(t: str) -> int:
    """Convert 'HH:MM:SS' (possibly >24h, e.g. '25:10:00') to seconds since midnight."""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def load_raw():
    print("Loading raw GTFS files...")
    stops = pd.read_csv(RAW_DIR / "stops.txt")
    routes = pd.read_csv(RAW_DIR / "routes.txt")
    trips = pd.read_csv(RAW_DIR / "trips.txt")
    calendar = pd.read_csv(RAW_DIR / "calendar.txt")
    stop_times = pd.read_csv(RAW_DIR / "stop_times.txt")
    return stops, routes, trips, calendar, stop_times


def build_dim_stops(stops: pd.DataFrame) -> pd.DataFrame:
    dim = stops.rename(columns={"stop_lat": "latitude", "stop_lon": "longitude"})
    return dim[["stop_id", "stop_name", "latitude", "longitude"]]


def build_dim_routes(routes: pd.DataFrame) -> pd.DataFrame:
    route_type_map = {3: "Bus"}  # GTFS route_type 3 = Bus
    dim = routes.copy()
    dim["route_type_desc"] = dim["route_type"].map(route_type_map).fillna("Other")
    return dim[["route_id", "route_short_name", "route_long_name", "route_type_desc"]]


def build_dim_calendar(calendar: pd.DataFrame) -> pd.DataFrame:
    return calendar


def build_dim_trips(trips: pd.DataFrame) -> pd.DataFrame:
    return trips[["trip_id", "route_id", "service_id", "trip_headsign", "direction_id", "shape_id"]]


def build_fact_stop_times(stop_times: pd.DataFrame) -> pd.DataFrame:
    print("Converting GTFS times to seconds-since-midnight (handles >24h trips)...")
    fact = stop_times.copy()
    fact["arrival_sec"] = fact["arrival_time"].apply(time_to_seconds)
    fact["departure_sec"] = fact["departure_time"].apply(time_to_seconds)
    fact["hour_of_day"] = (fact["arrival_sec"] // 3600) % 24  # normalize past-midnight hours
    return fact[[
        "trip_id", "stop_id", "stop_sequence",
        "arrival_time", "departure_time", "arrival_sec", "departure_sec", "hour_of_day",
    ]]


def write_to_duckdb(dim_stops, dim_routes, dim_calendar, dim_trips, fact_stop_times):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()  # rebuild fresh each run

    con = duckdb.connect(str(DB_PATH))

    con.execute("CREATE TABLE dim_stops AS SELECT * FROM dim_stops")
    con.execute("CREATE TABLE dim_routes AS SELECT * FROM dim_routes")
    con.execute("CREATE TABLE dim_calendar AS SELECT * FROM dim_calendar")
    con.execute("CREATE TABLE dim_trips AS SELECT * FROM dim_trips")
    con.execute("CREATE TABLE fact_stop_times AS SELECT * FROM fact_stop_times")

    # Primary-key-style indexes for join performance
    con.execute("CREATE INDEX idx_stops_id ON dim_stops(stop_id)")
    con.execute("CREATE INDEX idx_routes_id ON dim_routes(route_id)")
    con.execute("CREATE INDEX idx_trips_id ON dim_trips(trip_id)")
    con.execute("CREATE INDEX idx_trips_route ON dim_trips(route_id)")
    con.execute("CREATE INDEX idx_fact_stop ON fact_stop_times(stop_id)")
    con.execute("CREATE INDEX idx_fact_trip ON fact_stop_times(trip_id)")

    print("\nTables written to DuckDB:")
    for row in con.execute("SHOW TABLES").fetchall():
        table = row[0]
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:20s} {count:>8,} rows")

    # Also export small dimension tables as CSV. The dashboard reads these
    # directly so deployment doesn't need to ship the (larger) DuckDB binary.
    con.execute(f"COPY dim_stops TO '{DB_PATH.parent / 'dim_stops.csv'}' (HEADER, DELIMITER ',')")
    con.execute(f"COPY dim_routes TO '{DB_PATH.parent / 'dim_routes.csv'}' (HEADER, DELIMITER ',')")
    print("Exported dim_stops.csv and dim_routes.csv for lightweight dashboard use")

    con.close()


if __name__ == "__main__":
    stops, routes, trips, calendar, stop_times = load_raw()

    dim_stops = build_dim_stops(stops)
    dim_routes = build_dim_routes(routes)
    dim_calendar = build_dim_calendar(calendar)
    dim_trips = build_dim_trips(trips)
    fact_stop_times = build_fact_stop_times(stop_times)

    write_to_duckdb(dim_stops, dim_routes, dim_calendar, dim_trips, fact_stop_times)
    print(f"\nStar schema saved to: {DB_PATH}")
