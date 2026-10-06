import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

plt.rcParams.update({"font.size": 16})
sns.set_theme(style="whitegrid", font_scale=1.2)

EXPERIMENT = "s5"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}
SENSORS = [2, 4, 8, 16, 32, 64]
START = 300
END = 900

root = Path("results/smartBuilding") / EXPERIMENT

if not root.exists():
    print(f"Warning: Root directory does not exist: {root.resolve()}")

BS_COLUMNS = ["epoch_ns", "event_type", "detail"]

def read_building_service(path):
    """Read building_service.csv, handling missing headers."""
    try:
        df = pd.read_csv(path)
        if "event_type" in df.columns:
            return df
        first_col = str(df.columns[0])
        if first_col.isdigit():
            df = pd.read_csv(path, header=None, names=BS_COLUMNS)
            return df
    except Exception:
        pass
    return pd.DataFrame()

# ==========================================
# 1. Load Data for all 4 Subplots (S5)
# ==========================================

# (a) Convergence Time Data
convergence_records = []
for sys_key, sys_label in systems.items():
    sys_path = root / sys_key
    if not sys_path.exists():
        continue
    for sensor_count in SENSORS:
        sensor_path = sys_path / str(sensor_count)
        if not sensor_path.exists():
            continue
        sim_df = None
        for sf in sensor_path.rglob("simulation.csv"):
            df = pd.read_csv(sf)
            if not df.empty and "fire_started_ns" in df.columns:
                sim_df = df
                break
        if sim_df is None or sim_df.empty:
            continue
        all_door_closes = []
        for bsf in sensor_path.rglob("building_service.csv"):
            bs_df = read_building_service(bsf)
            if bs_df.empty or "event_type" not in bs_df.columns:
                continue
            closes = bs_df[bs_df["event_type"] == "door_close"]["epoch_ns"].values
            all_door_closes.extend(closes)
        if len(all_door_closes) == 0:
            continue
        all_door_closes = np.sort(all_door_closes)
        fire_starts = sim_df["fire_started_ns"].values
        for i in range(len(fire_starts)):
            window_start = fire_starts[i]
            window_end = fire_starts[i + 1] if i + 1 < len(fire_starts) else fire_starts[i] + 300_000_000_000
            mask = (all_door_closes >= window_start) & (all_door_closes < window_end)
            matching = all_door_closes[mask]
            if len(matching) == 0:
                continue
            convergence_ms = (matching[-1] - fire_starts[i]) / 1_000_000.0
            if convergence_ms > 0:
                convergence_records.append({
                    "System": sys_label,
                    "Sensors": sensor_count,
                    "Convergence Time (ms)": convergence_ms,
                })
df_convergence = pd.DataFrame(convergence_records)

# (b) Event Latency Data
latency_records = []
for sys_key, sys_label in systems.items():
    sys_path = root / sys_key
    if not sys_path.exists():
        continue
    for sensor_count in SENSORS:
        sensor_path = sys_path / str(sensor_count)
        if not sensor_path.exists():
            continue
        for file_path in sensor_path.rglob("event.latency.csv"):
            try:
                df = pd.read_csv(file_path)
            except Exception:
                continue
            if df.empty or "t" not in df.columns:
                continue
            df["t"] = (df["t"] - df["t"].iloc[0]).astype(int)
            df = df.groupby("t")["mean"].mean().to_frame().sort_index()
            df = df.loc[START:END]
            df = df[df["mean"] > 0].dropna()
            for val in df["mean"].tolist():
                latency_records.append({
                    "System": sys_label,
                    "Sensors": sensor_count,
                    "Latency (ms)": val,
                })
df_latency = pd.DataFrame(latency_records)

# (d) Propagation Time Data
propagation_records = []
for sys_key, sys_label in systems.items():
    sys_path = root / sys_key
    if not sys_path.exists():
        continue
    for sensor_count in SENSORS:
        sensor_path = sys_path / str(sensor_count)
        if not sensor_path.exists():
            continue
        sim_df = None
        for sf in sensor_path.rglob("simulation.csv"):
            df = pd.read_csv(sf)
            if not df.empty and "fire_detected_ns" in df.columns:
                sim_df = df
                break
        if sim_df is None or sim_df.empty:
            continue
        all_door_closes = []
        for bsf in sensor_path.rglob("building_service.csv"):
            bs_df = read_building_service(bsf)
            if bs_df.empty or "event_type" not in bs_df.columns:
                continue
            closes = bs_df[bs_df["event_type"] == "door_close"]["epoch_ns"].values
            all_door_closes.extend(closes)
        if len(all_door_closes) == 0:
            continue
        all_door_closes = np.sort(all_door_closes)
        fire_starts = sim_df["fire_started_ns"].values
        fire_detects = sim_df["fire_detected_ns"].values
        for i in range(len(fire_starts)):
            window_start = fire_starts[i]
            window_end = fire_starts[i + 1] if i + 1 < len(fire_starts) else fire_starts[i] + 300_000_000_000
            mask = (all_door_closes >= window_start) & (all_door_closes < window_end)
            matching = all_door_closes[mask]
            if len(matching) == 0:
                continue
            propagation_ms = (matching[-1] - fire_detects[i]) / 1_000_000.0
            if propagation_ms > 0:
                propagation_records.append({
                    "System": sys_label,
                    "Sensors": sensor_count,
                    "Propagation Time (ms)": propagation_ms,
                })
df_propagation = pd.DataFrame(propagation_records)

# ==========================================
# 2. Build 2x2 Subplot Figure (Matched with target style)
# ==========================================

cmap = plt.get_cmap("Set1")
output_path = Path("figure") / EXPERIMENT
output_path.mkdir(parents=True, exist_ok=True)

fig, axes = plt.subplots(nrows=1, ncols=3, figsize=(10, 3))
axes = axes.flatten()

configs = [
    (df_convergence, "Convergence Time (ms)", "(a) Convergence Time", "convergence_time"),
    (df_latency, "Latency (ms)", "(b) Event Latency", "event_latency"),
    (df_propagation, "Propagation Time (ms)", "(d) Propagation Time", "propagation_time"),
]

labels = ["Convergence Time (ms)", "Event Latency (ms)", "Propagation Time (ms)"]

for idx, (ax, (df, y_col, title, filename_prefix)) in enumerate(zip(axes, configs)):
    if not df.empty:
        # Check if it's convergence or propagation (line plots) vs latency or invoke (box/errorbar or line)
        # The user reference template uses errorbar/line plots with cmap and error bars or standard line plots with fill_between.
        # Let's use the errorbar or line style matching the smartfactory reference code.
        for i, (sys_key, sys_label) in enumerate(systems.items()):
            sub = df[df["System"] == sys_label]
            if sub.empty:
                continue
            grouped = sub.groupby("Sensors")[y_col]
            means = grouped.mean()
            stds = grouped.std().fillna(0)

            ax.errorbar(
                means.index,
                means.values,
                yerr=stds.values,
                marker="o",
                linewidth=2,
                markersize=7,
                capsize=5,
                elinewidth=1.5,
                capthick=1.5,
                color=cmap(i),
                alpha=0.7 if i == 0 else 1.0,
                label=sys_label,
            )

        ax.set_xscale("log", base=2)
        if (y_col == "Convergence Time (ms)"):
            ax.ticklabel_format(style="sci", axis="y", scilimits=(0, 0))
        ax.set_xticks(SENSORS)
        ax.set_xticklabels([str(s) for s in SENSORS])
        ax.grid(True, which="major", linestyle="--", alpha=0.3)
        ax.set_axisbelow(True)
        if idx == 0:
            ax.legend(frameon=False)
    else:
        ax.text(0.5, 0.5, "No Data Available", ha="center", va="center", transform=ax.transAxes)

    ax.set_xlabel("Number of Sensors")
    ax.set_ylabel(labels[idx])

fig.subplots_adjust(
    left=0.08,
    right=0.99,
    top=0.92,
    bottom=0.10,
    wspace=0.30,
    hspace=0.25,
)

plt.tight_layout()

pdf_file = output_path / "s5_combined_metrics.pdf"
png_file = output_path / "s5_combined_metrics.png"

plt.savefig(pdf_file, bbox_inches="tight", dpi=300)
plt.savefig(png_file, bbox_inches="tight", dpi=300)
plt.close(fig)

print(f"Successfully saved combined 2x2 figure to:\n - {pdf_file}\n - {png_file}")