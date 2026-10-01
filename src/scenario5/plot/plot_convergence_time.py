import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid", font_scale=1.2)

EXPERIMENT = "s5"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}
SENSORS = [2, 4, 8, 16, 32, 64]

root = Path("results/smartBuilding") / EXPERIMENT

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


plot_records = []

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
            print(f"  [WARN] No simulation.csv for {sys_label} sensors={sensor_count}")
            continue

        all_door_closes = []
        for bsf in sensor_path.rglob("building_service.csv"):
            bs_df = read_building_service(bsf)
            if bs_df.empty or "event_type" not in bs_df.columns:
                continue
            closes = bs_df[bs_df["event_type"] == "door_close"]["epoch_ns"].values
            all_door_closes.extend(closes)

        if len(all_door_closes) == 0:
            print(f"  [WARN] No door_close events for {sys_label} sensors={sensor_count}")
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
                plot_records.append({
                    "System": sys_label,
                    "Sensors": sensor_count,
                    "Convergence Time (ms)": convergence_ms,
                })

df_plot = pd.DataFrame(plot_records)

fig, ax = plt.subplots(figsize=(10, 5))

if not df_plot.empty:
    palette = {"Cirrina": "#1f77b4", "Dapr": "#ff7f0e"}

    for sys_label, color in palette.items():
        sub = df_plot[df_plot["System"] == sys_label]
        if sub.empty:
            continue
        grouped = sub.groupby("Sensors")["Convergence Time (ms)"]
        means = grouped.mean()
        stds = grouped.std().fillna(0)

        ax.plot(means.index, means.values, "o-", color=color, label=sys_label,
                linewidth=2, markersize=7, zorder=3)
        ax.fill_between(means.index, (means - stds).values, (means + stds).values,
                        alpha=0.15, color=color, zorder=2)

    ax.set_xlabel("Number of Sensors")
    ax.set_ylabel("Convergence Time (ms)")
    ax.set_xscale("log", base=2)
    ax.set_xticks(SENSORS)
    ax.set_xticklabels([str(s) for s in SENSORS])
    ax.legend(frameon=True, fancybox=False, edgecolor="gray")
    ax.grid(True, linestyle="--", alpha=0.4)

plt.tight_layout()

output_path = f"figure/{EXPERIMENT}"
os.makedirs(output_path, exist_ok=True)
plt.savefig(os.path.join(output_path, "convergence_time.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(output_path, "convergence_time.png"), bbox_inches="tight", dpi=300)

if not df_plot.empty:
    print("\n=== Convergence Time Summary ===")
    summary = df_plot.groupby(["System", "Sensors"])["Convergence Time (ms)"].agg(["mean", "std", "count"])
    print(summary.to_string())
