import os
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams.update({"font.size": 14})

EXPERIMENT = "s2"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}

# Custom RGBA Hex Colors
colors = [
    "#33B24C80",
    "#4C4C9980",
    "#801ACC80",
    "#E6998080",
]

START = 300
END = 900

root = Path("results/smartBuilding") / EXPERIMENT

if not root.exists():
    print(f"Warning: Root directory does not exist: {root.resolve()}")

# ==========================================
# 1. Helper Functions to Load Metric Data
# ==========================================

def load_csv_metric(filename, value_column_name):
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for metrics_path in root.glob("*/*/*/metrics"):
        parts = metrics_path.parts
        sys_key, run, host = parts[-4], parts[-3], parts[-2]

        if sys_key not in systems:
            continue

        file_path = metrics_path / filename
        if file_path.exists():
            df = pd.read_csv(file_path)
            if df.empty or "t" not in df.columns:
                continue
            df["t"] = (df["t"] - df["t"].iloc[0]).astype(int)
            df = df.groupby("t")["mean"].mean().to_frame()
            df = df.sort_index()
            df = df.loc[START:END]
            df = df[df["mean"] > 0].dropna()
            if not df.empty:
                df.index = df.index - START
                data[sys_key][run][host] = df

    records = []
    for sys_key, sys_label in systems.items():
        if sys_key in data:
            for run in data[sys_key]:
                for host, df in data[sys_key][run].items():
                    for val in df["mean"].tolist():
                        records.append({"System": sys_label, value_column_name: val})
    return pd.DataFrame(records)


def load_response_time_data():
    records = []
    for sys_key, sys_label in systems.items():
        sys_path = root / sys_key
        if not sys_path.exists():
            continue
        for run_dir in sorted(sys_path.glob("run*")):
            all_occupancy_detects = []
            all_consumer_actions = []

            for host_dir in run_dir.iterdir():
                bs_csv = host_dir / "metrics" / "building_service.csv"
                if not bs_csv.exists():
                    continue
                df = pd.read_csv(bs_csv)
                if df.empty or "event_type" not in df.columns:
                    continue

                # Only positive detections (detail == "true")
                occ = df[
                    (df["event_type"] == "occupancy_detect")
                    & (df["detail"].astype(str).str.lower() == "true")
                ]["epoch_ns"].values

                # Consumer reactions: hvac_action, hvac_consumer, lighting_action, or light_consumer
                cons = df[
                    df["event_type"].isin(
                        ["hvac_action", "hvac_consumer", "lighting_action", "light_consumer"]
                    )
                ]["epoch_ns"].values

                all_occupancy_detects.extend(occ)
                all_consumer_actions.extend(cons)

            all_occupancy_detects = np.sort(all_occupancy_detects)
            all_consumer_actions = np.sort(all_consumer_actions)

            if len(all_occupancy_detects) == 0 or len(all_consumer_actions) == 0:
                continue

            cons_idx = 0
            for detect_ns in all_occupancy_detects:
                while cons_idx < len(all_consumer_actions) and all_consumer_actions[cons_idx] < detect_ns:
                    cons_idx += 1
                if cons_idx < len(all_consumer_actions):
                    response_ms = (all_consumer_actions[cons_idx] - detect_ns) / 1_000_000.0
                    rel_sec = (detect_ns - all_occupancy_detects[0]) / 1_000_000_000.0
                    if START <= rel_sec <= END and 0 < response_ms < 10000:
                        records.append({"System": sys_label, "Convergence Time (ms)": response_ms})

    return pd.DataFrame(records)

# ==========================================
# 2. Extract Data
# ==========================================

df_event_latency = load_csv_metric("event.latency.csv", "Latency (ms)")
df_invoke_time = load_csv_metric("invoke.time.csv", "Invoke Time (ms)")
df_convergence_time = load_response_time_data()

# ==========================================
# 3. Build 1x3 Subplot Figure
# ==========================================

fig, axes = plt.subplots(nrows=1, ncols=3, figsize=(15, 3))

configs = [
    (df_event_latency, "Latency (ms)", "(a) Event Latency"),
    (df_invoke_time, "Invoke Time (ms)", "(b) Service Invoke Time"),
    (df_convergence_time, "Convergence Time (ms)", "(c) Convergence Time"),
]

labels = list(systems.values())

# Properties to render small orange dots for outliers
flier_props = dict(
    marker="o",
    markerfacecolor="orange",
    markeredgecolor="orange",
    markersize=3,
    alpha=0.7,
)

for ax, (df, y_col, title) in zip(axes, configs):
    if not df.empty:
        plot_data = [
            df[df["System"] == label][y_col].dropna().values
            for label in labels
        ]

        bplot = ax.boxplot(
            plot_data,
            vert=True,
            patch_artist=True,
            tick_labels=labels,
            widths=0.15,
            flierprops=flier_props,
        )

        for patch, color in zip(bplot["boxes"], colors):
            patch.set_facecolor(color)
    else:
        ax.text(0.5, 0.5, "No Data Available", ha="center", va="center", transform=ax.transAxes)

    ax.set_ylabel(y_col)
    ax.yaxis.grid(True, linestyle="--", alpha=0.7)

plt.tight_layout()

# ==========================================
# 4. Save Figures
# ==========================================

script_dir = Path(__file__).resolve().parent
output_path = script_dir / "figures"
output_path.mkdir(parents=True, exist_ok=True)

pdf_file = output_path / "s2_combined_metrics.pdf"

plt.savefig(pdf_file, bbox_inches="tight")
plt.close(fig)

print(f"Successfully saved combined 1x3 boxplot figure to:\n - {pdf_file}")