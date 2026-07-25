import duckdb
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "pmpml.duckdb"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "route_crowding_risk.csv"

MORNING_PEAK = (7, 10)   # 7:00-9:59
EVENING_PEAK = (17, 20)  # 17:00-19:59


def load_peak_stop_times(con):
    query = f"""
        SELECT
            f.trip_id, f.stop_id, f.arrival_sec, f.hour_of_day,
            t.route_id, r.route_short_name, r.route_long_name
        FROM fact_stop_times f
        JOIN dim_trips t   ON f.trip_id = t.trip_id
        JOIN dim_routes r  ON t.route_id = r.route_id
        WHERE (f.hour_of_day >= {MORNING_PEAK[0]} AND f.hour_of_day < {MORNING_PEAK[1]})
           OR (f.hour_of_day >= {EVENING_PEAK[0]} AND f.hour_of_day < {EVENING_PEAK[1]})
    """
    return con.execute(query).df()


def compute_headways(df: pd.DataFrame) -> pd.DataFrame:
    """For each (route, stop), sort arrivals and compute gaps between consecutive buses."""
    df = df.sort_values(["route_id", "stop_id", "arrival_sec"])
    df["prev_arrival"] = df.groupby(["route_id", "stop_id"])["arrival_sec"].shift(1)
    df["headway_min"] = (df["arrival_sec"] - df["prev_arrival"]) / 60.0
    return df.dropna(subset=["headway_min"])


def compute_route_risk(headways: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate to route level:
      - avg_headway_min: average wait between buses (lower = more frequent = better)
      - headway_std: consistency of service (lower = more predictable = better)
      - crowding_risk_score: composite -- routes with long AND unpredictable
        headways score highest risk
    """
    agg = headways.groupby(["route_id", "route_short_name", "route_long_name"]).agg(
        avg_headway_min=("headway_min", "mean"),
        headway_std=("headway_min", "std"),
        peak_trip_count=("trip_id", "nunique"),
        stops_served=("stop_id", "nunique"),
    ).reset_index()

    agg["headway_std"] = agg["headway_std"].fillna(0)

    # Normalize both components 0-1, combine into a single risk score.
    # Weighted toward avg_headway since long average wait is the bigger risk driver.
    def normalize(s):
        return (s - s.min()) / (s.max() - s.min() + 1e-9)

    agg["headway_score"] = normalize(agg["avg_headway_min"])
    agg["variability_score"] = normalize(agg["headway_std"])
    agg["crowding_risk_score"] = (0.7 * agg["headway_score"] + 0.3 * agg["variability_score"])

    agg = agg.sort_values("crowding_risk_score", ascending=False).reset_index(drop=True)
    agg["risk_rank"] = agg.index + 1
    return agg


if __name__ == "__main__":
    con = duckdb.connect(str(DB_PATH))

    print("Loading peak-hour stop times...")
    peak_df = load_peak_stop_times(con)
    print(f"  {len(peak_df):,} peak-hour stop-time records loaded")

    print("Computing headways (gap between consecutive buses per route/stop)...")
    headways = compute_headways(peak_df)
    print(f"  {len(headways):,} headway observations computed")

    print("Aggregating to route-level crowding risk score...")
    risk = compute_route_risk(headways)

    risk.to_csv(OUT_PATH, index=False)
    print(f"\nSaved: {OUT_PATH}")

    print("\n" + "=" * 70)
    print("TOP 10 HIGHEST CROWDING-RISK ROUTES (peak hours)")
    print("=" * 70)
    top10 = risk.head(10)[[
        "risk_rank", "route_short_name", "route_long_name",
        "avg_headway_min", "headway_std", "peak_trip_count", "crowding_risk_score",
    ]]
    with pd.option_context("display.max_colwidth", 40, "display.width", 140):
        print(top10.to_string(index=False))

    print(f"\nTotal routes analyzed: {len(risk)}")
    print(f"Median peak-hour headway across network: {risk['avg_headway_min'].median():.1f} min")

    con.close()
