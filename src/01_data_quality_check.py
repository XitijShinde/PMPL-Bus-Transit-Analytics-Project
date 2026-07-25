import pandas as pd
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

FILES = [
    "agency.txt", "calendar.txt", "feed_info.txt",
    "routes.txt", "stops.txt", "trips.txt",
    "stop_times.txt", "shapes.txt",
]


def load_all():
    dfs = {}
    for f in FILES:
        name = f.replace(".txt", "")
        dfs[name] = pd.read_csv(RAW_DIR / f)
    return dfs


def summarize_shapes(dfs):
    print("=" * 60)
    print("FILE SHAPES")
    print("=" * 60)
    for name, df in dfs.items():
        print(f"{name:15s} rows={len(df):>8,}  cols={list(df.columns)}")


def check_nulls(dfs):
    print("\n" + "=" * 60)
    print("NULL VALUE CHECK")
    print("=" * 60)
    for name, df in dfs.items():
        nulls = df.isnull().sum()
        nulls = nulls[nulls > 0]
        if len(nulls) == 0:
            print(f"{name:15s} -> no nulls")
        else:
            print(f"{name:15s} -> {dict(nulls)}")


def check_duplicates(dfs):
    print("\n" + "=" * 60)
    print("DUPLICATE ROW CHECK")
    print("=" * 60)
    for name, df in dfs.items():
        dupes = df.duplicated().sum()
        print(f"{name:15s} -> {dupes:,} fully duplicated rows")

    # Key-level duplicate checks (more meaningful than full-row dupes)
    print("\n-- key-level duplicate checks --")
    dupe_stops = dfs["stops"]["stop_id"].duplicated().sum()
    print(f"stops.stop_id duplicated:        {dupe_stops:,}")

    dupe_trips = dfs["trips"]["trip_id"].duplicated().sum()
    print(f"trips.trip_id duplicated:        {dupe_trips:,}")

    dupe_routes = dfs["routes"]["route_id"].duplicated().sum()
    print(f"routes.route_id duplicated:      {dupe_routes:,}")

    dupe_stop_seq = dfs["stop_times"].duplicated(
        subset=["trip_id", "stop_sequence"]
    ).sum()
    print(f"stop_times (trip_id,seq) dupes:  {dupe_stop_seq:,}")


def check_referential_integrity(dfs):
    print("\n" + "=" * 60)
    print("REFERENTIAL INTEGRITY CHECK")
    print("=" * 60)

    # every stop_id in stop_times must exist in stops
    valid_stops = set(dfs["stops"]["stop_id"])
    st_stops = set(dfs["stop_times"]["stop_id"])
    orphan_stops = st_stops - valid_stops
    print(f"stop_times -> stops:      {len(orphan_stops):,} orphan stop_ids "
          f"(out of {len(st_stops):,} distinct)")

    # every trip_id in stop_times must exist in trips
    valid_trips = set(dfs["trips"]["trip_id"])
    st_trips = set(dfs["stop_times"]["trip_id"])
    orphan_trips = st_trips - valid_trips
    print(f"stop_times -> trips:      {len(orphan_trips):,} orphan trip_ids "
          f"(out of {len(st_trips):,} distinct)")

    # every route_id in trips must exist in routes
    valid_routes = set(dfs["routes"]["route_id"])
    tr_routes = set(dfs["trips"]["route_id"])
    orphan_routes = tr_routes - valid_routes
    print(f"trips -> routes:          {len(orphan_routes):,} orphan route_ids "
          f"(out of {len(tr_routes):,} distinct)")

    # every service_id in trips must exist in calendar
    valid_services = set(dfs["calendar"]["service_id"])
    tr_services = set(dfs["trips"]["service_id"])
    orphan_services = tr_services - valid_services
    print(f"trips -> calendar:        {len(orphan_services):,} orphan service_ids "
          f"(out of {len(tr_services):,} distinct)")

    # every shape_id in trips (if present) must exist in shapes
    if "shape_id" in dfs["trips"].columns:
        valid_shapes = set(dfs["shapes"]["shape_id"])
        tr_shapes = set(dfs["trips"]["shape_id"].dropna())
        orphan_shapes = tr_shapes - valid_shapes
        print(f"trips -> shapes:          {len(orphan_shapes):,} orphan shape_ids "
              f"(out of {len(tr_shapes):,} distinct)")


def summarize_coverage(dfs):
    print("\n" + "=" * 60)
    print("COVERAGE SUMMARY")
    print("=" * 60)
    print(f"Total routes:              {dfs['routes']['route_id'].nunique():,}")
    print(f"Total stops:               {dfs['stops']['stop_id'].nunique():,}")
    print(f"Total trips:               {dfs['trips']['trip_id'].nunique():,}")
    print(f"Total stop_time records:   {len(dfs['stop_times']):,}")
    avg_stops_per_trip = len(dfs["stop_times"]) / dfs["trips"]["trip_id"].nunique()
    print(f"Avg stops per trip:        {avg_stops_per_trip:.1f}")

    lat_min, lat_max = dfs["stops"]["stop_lat"].min(), dfs["stops"]["stop_lat"].max()
    lon_min, lon_max = dfs["stops"]["stop_lon"].min(), dfs["stops"]["stop_lon"].max()
    print(f"Stop lat range:            {lat_min:.4f} to {lat_max:.4f}")
    print(f"Stop lon range:            {lon_min:.4f} to {lon_max:.4f}")


if __name__ == "__main__":
    dfs = load_all()
    summarize_shapes(dfs)
    check_nulls(dfs)
    check_duplicates(dfs)
    check_referential_integrity(dfs)
    summarize_coverage(dfs)
