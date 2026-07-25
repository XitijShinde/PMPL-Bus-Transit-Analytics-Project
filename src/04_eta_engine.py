import duckdb
import pandas as pd
import networkx as nx
from pathlib import Path
import time

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "pmpml.duckdb"
GRAPH_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "stop_graph.gpickle"


def load_consecutive_stop_pairs(con) -> pd.DataFrame:
    """
    For every trip, pair each stop with the NEXT stop in its sequence,
    and compute the scheduled travel time between them.
    """
    query = """
        SELECT
            trip_id, stop_id, stop_sequence, departure_sec
        FROM fact_stop_times
        ORDER BY trip_id, stop_sequence
    """
    df = con.execute(query).df()

    df["next_stop_id"] = df.groupby("trip_id")["stop_id"].shift(-1)
    df["next_departure_sec"] = df.groupby("trip_id")["departure_sec"].shift(-1)
    df["travel_sec"] = df["next_departure_sec"] - df["departure_sec"]

    pairs = df.dropna(subset=["next_stop_id", "travel_sec"]).copy()
    pairs = pairs[pairs["travel_sec"] > 0]  # drop bad/duplicate-timestamp edges
    pairs["next_stop_id"] = pairs["next_stop_id"].astype(int)
    return pairs[["stop_id", "next_stop_id", "travel_sec"]]


def build_graph(pairs: pd.DataFrame, dim_stops: pd.DataFrame) -> nx.DiGraph:
    """Weight each edge by the median travel time across all trips using it."""
    edge_weights = pairs.groupby(["stop_id", "next_stop_id"])["travel_sec"].median().reset_index()

    G = nx.DiGraph()
    name_map = dict(zip(dim_stops["stop_id"], dim_stops["stop_name"]))
    for stop_id, name in name_map.items():
        G.add_node(stop_id, name=name)

    for _, row in edge_weights.iterrows():
        G.add_edge(int(row["stop_id"]), int(row["next_stop_id"]), weight=row["travel_sec"])

    return G


def compute_eta(G: nx.DiGraph, origin_stop_id: int, dest_stop_id: int):
    """Dijkstra shortest (fastest) path between two stops. Returns (total_seconds, path_stop_ids)."""
    try:
        total_sec, path = nx.single_source_dijkstra(G, origin_stop_id, dest_stop_id, weight="weight")
        return total_sec, path
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None, None


if __name__ == "__main__":
    con = duckdb.connect(str(DB_PATH))
    dim_stops = con.execute("SELECT * FROM dim_stops").df()

    print("Building stop-to-stop travel time pairs from schedule...")
    pairs = load_consecutive_stop_pairs(con)
    print(f"  {len(pairs):,} raw consecutive-stop observations")

    print("Building directed graph (median travel time per edge)...")
    G = build_graph(pairs, dim_stops)
    print(f"  Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

    # Persist edge list + node names as CSV (portable, avoids pickle version issues)
    out_dir = Path(__file__).resolve().parent.parent / "data" / "processed"
    nx.to_pandas_edgelist(G).to_csv(out_dir / "stop_graph_edges.csv", index=False)
    dim_stops.to_csv(out_dir / "stop_graph_nodes.csv", index=False)
    print(f"  Saved graph edges/nodes to {out_dir}")

    # --- Demo: compute ETA between two real stops ---
    sample = dim_stops.sample(2, random_state=42)
    origin_id, origin_name = int(sample.iloc[0]["stop_id"]), sample.iloc[0]["stop_name"]
    dest_id, dest_name = int(sample.iloc[1]["stop_id"]), sample.iloc[1]["stop_name"]

    print(f"\nDemo query: '{origin_name}' -> '{dest_name}'")
    start = time.perf_counter()
    total_sec, path = compute_eta(G, origin_id, dest_id)
    elapsed_ms = (time.perf_counter() - start) * 1000

    if total_sec is None:
        print(f"  No scheduled path found between these two stops (network is not fully connected).")
    else:
        name_map = dict(zip(dim_stops["stop_id"], dim_stops["stop_name"]))
        path_names = [name_map.get(s, str(s)) for s in path]
        print(f"  ETA: {total_sec/60:.1f} minutes via {len(path)} stops")
        print(f"  Route: {' -> '.join(path_names[:5])}{' ...' if len(path_names) > 5 else ''}")
    print(f"  Query time: {elapsed_ms:.2f} ms")

    con.close()
