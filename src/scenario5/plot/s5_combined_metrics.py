import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams.update({"font.size": 14})

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
# 1. Load Data for all 4 Subplots
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

# (c) Invoke Time Data
invoke_records = []
for sys_key, sys_label in systems.items():
    sys_path = root / sys_key
    if not sys_path.exists():
        continue
    for sensor_count in SENSORS:
        sensor_path = sys_path / str(sensor_count)
        if not sensor_path.exists():
            continue
        for file_path in sensor_path.rglob("invoke.time.csv"):
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
                invoke_records.append({
                    "System": sys_label,
                    "Sensors": sensor_count,
                    "Invoke Time (ms)": val,
                })
df_invoke = pd.DataFrame(invoke_records)

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
# 2. Build 2x2 Subplot Figure (Pure Matplotlib style matching s1-gas)
# ==========================================

fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(14, 8))
axes = axes.flatten()

# Custom RGBA Hex Colors
colors = [
    "#33B24C80",
    "#4C4C9980",
    "#801ACC80",
    "#E6998080",
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

configs = [
    (df_convergence, "Convergence Time (ms)", "(a) Convergence Time", True),
    (df_latency, "Latency (ms)", "(b) Event Latency", False),
    (df_invoke, "Invoke Time (ms)", "(c) Service Invoke Time", False),
    (df_propagation, "Propagation Time (ms)", "(d) Propagation Time", True),
]

for ax, (df, y_col, title, is_line) in zip(axes, configs):
    if not df.empty:
        if is_line:
            line_colors = {"Cirrina": "#33B24C", "Dapr": "#4C4C99"}
            for sys_label, color in line_colors.items():
                sub = df[df["System"] == sys_label]
                if sub.empty:
                    continue
                grouped = sub.groupby("Sensors")[y_col]
                means = grouped.mean()
                stds = grouped.std().fillna(0)
                ax.plot(means.index, means.values, "o-", color=color, label=sys_label, linewidth=2, markersize=6,
                        zorder=3)
                ax.fill_between(means.index, (means - stds).values, (means + stds).values, alpha=0.15, color=color,
                                zorder=2)
            ax.set_xscale("log", base=2)
            ax.set_xticks(SENSORS)
            ax.set_xticklabels([str(s) for s in SENSORS])

            # Use scientific notation for the y-axis
            ax.ticklabel_format(style="sci", axis="y", scilimits=(0, 0))

            ax.legend(frameon=True, fancybox=False, edgecolor="gray")
        else:
            plot_data = []
            for sensor_count in SENSORS:
                sensor_data = []
                for label in labels:
                    vals = df[(df["Sensors"] == sensor_count) & (df["System"] == label)][y_col].dropna().values
                    sensor_data.append(vals)
                plot_data.append(sensor_data)

            positions = []
            widths = 0.35
            delta = 0.2

            for i, sensor_count in enumerate(SENSORS):
                base_pos = i * 2.0
                pos_sys1 = base_pos - delta
                pos_sys2 = base_pos + delta
                positions.extend([pos_sys1, pos_sys2])

            flat_plot_data = []
            for sensor_count in SENSORS:
                for label in labels:
                    vals = df[(df["Sensors"] == sensor_count) & (df["System"] == label)][y_col].dropna().values
                    flat_plot_data.append(vals)

            bplot = ax.boxplot(
                flat_plot_data,
                positions=positions,
                vert=True,
                patch_artist=True,
                widths=widths,
                flierprops=flier_props,
            )

            for patch, color in zip(bplot["boxes"], [colors[0], colors[1]] * len(SENSORS)):
                patch.set_facecolor(color)

            ax.set_xticks([i * 2.0 for i in range(len(SENSORS))])
            ax.set_xticklabels([str(s) for s in SENSORS])

            from matplotlib.patches import Patch

            legend_elements = [
                Patch(facecolor=colors[0], edgecolor='k', label=labels[0]),
                Patch(facecolor=colors[1], edgecolor='k', label=labels[1])
            ]
            ax.legend(handles=legend_elements, frameon=True, fancybox=False, edgecolor="gray")
    else:
        ax.text(0.5, 0.5, "No Data Available", ha="center", va="center", transform=ax.transAxes)

    ax.set_xlabel("Number of Sensors")
    ax.set_ylabel(y_col)
    ax.yaxis.grid(True, linestyle="--", alpha=0.7)

plt.tight_layout()

# ==========================================
# 3. Save Figures
# ==========================================

output_path = Path("figure") / EXPERIMENT
output_path.mkdir(parents=True, exist_ok=True)

pdf_file = output_path / "s5_combined_metrics.pdf"
png_file = output_path / "s5_combined_metrics.png"

plt.savefig(pdf_file, bbox_inches="tight")
plt.savefig(png_file, bbox_inches="tight", dpi=300)
plt.close(fig)

print(f"Successfully saved combined 2x2 subplot figure to:\n - {pdf_file}\n - {png_file}")