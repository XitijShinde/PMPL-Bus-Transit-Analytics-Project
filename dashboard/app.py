import pandas as pd
import networkx as nx
import streamlit as st
import matplotlib.pyplot as plt
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

st.set_page_config(page_title="PMPML Transit Analytics", layout="wide")


@st.cache_data
def load_data():
    # Reads lightweight CSV exports only -- no DuckDB binary needed at deploy time.
    # (DuckDB is still used locally in src/02_build_star_schema.py to build these.)
    dim_stops = pd.read_csv(DATA_DIR / "dim_stops.csv")
    dim_routes = pd.read_csv(DATA_DIR / "dim_routes.csv")
    risk = pd.read_csv(DATA_DIR / "route_crowding_risk.csv")
    edges = pd.read_csv(DATA_DIR / "stop_graph_edges.csv")
    return dim_stops, dim_routes, risk, edges


@st.cache_resource
def build_graph(edges: pd.DataFrame):
    G = nx.from_pandas_edgelist(
        edges, source="source", target="target", edge_attr="weight", create_using=nx.DiGraph()
    )
    return G


dim_stops, dim_routes, risk, edges = load_data()
G = build_graph(edges)
name_to_id = dict(zip(dim_stops["stop_name"], dim_stops["stop_id"]))
id_to_name = dict(zip(dim_stops["stop_id"], dim_stops["stop_name"]))

st.title("PMPML Transit Accessibility & Reliability Analytics")
st.caption(
    "Built on Pune's real GTFS schedule feed — 495 routes, 6,203 stops, 455K+ scheduled trips. "
    "Crowding risk is a frequency-based proxy (headway analysis), not measured passenger counts."
)

tab1, tab2, tab3 = st.tabs([" Crowding Risk ", " Stop Coverage ", " ETA Calculator "])

with tab1:
    st.subheader("Peak-Hour Crowding Risk by Route")
    st.write(
        "Ranked by a composite score combining average headway (wait between buses) "
        "and headway variability during morning (7-10 AM) and evening (5-8 PM) peaks. "
        "Higher score = fewer, less predictable buses = higher crowding risk."
    )

    n = st.slider("Show top N highest-risk routes", 5, 50, 15)
    top_risk = risk.head(n)

    fig, ax = plt.subplots(figsize=(10, max(4, n * 0.3)))
    ax.barh(top_risk["route_short_name"].astype(str), top_risk["crowding_risk_score"], color="#d62728")
    ax.invert_yaxis()
    ax.set_xlabel("Crowding Risk Score (0-1)")
    ax.set_title(f"Top {n} Highest Crowding-Risk Routes (Peak Hours)")
    st.pyplot(fig)

    st.dataframe(
        top_risk[[
            "risk_rank", "route_short_name", "route_long_name",
            "avg_headway_min", "headway_std", "peak_trip_count", "crowding_risk_score",
        ]].rename(columns={
            "avg_headway_min": "Avg Wait (min)",
            "headway_std": "Wait Variability",
            "peak_trip_count": "Peak Trips",
            "crowding_risk_score": "Risk Score",
        }),
        use_container_width=True,
    )

    st.metric("Median peak-hour wait across network", f"{risk['avg_headway_min'].median():.1f} min")

with tab2:
    st.subheader("Stop Coverage Across Pune")
    st.write(f"All **{len(dim_stops):,} stops** in the PMPML network, plotted by location.")
    st.map(dim_stops.rename(columns={"latitude": "lat", "longitude": "lon"})[["lat", "lon"]])

    st.write("Route type breakdown:")
    st.dataframe(dim_routes["route_type_desc"].value_counts().rename_axis("Type").reset_index(name="Routes"))

with tab3:
    st.subheader("Stop-to-Stop ETA Calculator")
    st.write(
        "Computes the fastest scheduled path between two stops using Dijkstra's algorithm "
        "over the real schedule graph. Note: this follows a single connected route path — "
        "trips requiring a transfer between routes aren't yet modeled (~12% of stop pairs)."
    )

    col1, col2 = st.columns(2)
    stop_names = sorted(name_to_id.keys())
    origin_name = col1.selectbox("From stop", stop_names, index=0)
    dest_name = col2.selectbox("To stop", stop_names, index=1)

    if st.button("Calculate ETA"):
        origin_id, dest_id = name_to_id[origin_name], name_to_id[dest_name]
        try:
            total_sec, path = nx.single_source_dijkstra(G, origin_id, dest_id, weight="weight")
            path_names = [id_to_name.get(s, str(s)) for s in path]
            st.success(f"ETA: **{total_sec/60:.1f} minutes** via {len(path)} stops")
            with st.expander("Show full stop-by-stop path"):
                st.write(" → ".join(path_names))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            st.error("No direct scheduled path found between these two stops (may require a route transfer).")
