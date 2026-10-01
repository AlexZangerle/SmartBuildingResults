import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid", font_scale=1.2)

EXPERIMENT = "s4"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}
SENSORS = [2, 4, 8, 16, 32, 64]
START = 300
END = 900

root = Path("results/smartBuilding") / EXPERIMENT

plot_records = []

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
                plot_records.append({
                    "System": sys_label,
                    "Sensors": sensor_count,
                    "Invoke Time (ms)": val,
                })

df_plot = pd.DataFrame(plot_records)

fig, ax = plt.subplots(figsize=(10, 5))

if not df_plot.empty:
    palette = {"Cirrina": "#1f77b4", "Dapr": "#ff7f0e"}
    sns.boxplot(
        data=df_plot,
        x="Sensors",
        y="Invoke Time (ms)",
        hue="System",
        palette=palette,
        ax=ax,
        fliersize=2,
        linewidth=0.8,
    )
    ax.set_xlabel("Number of Sensors")
    ax.set_ylabel("Invoke Time (ms)")
    ax.legend(frameon=True, fancybox=False, edgecolor="gray")
    ax.grid(True, linestyle="--", alpha=0.4)

plt.tight_layout()

output_path = f"figure/{EXPERIMENT}"
os.makedirs(output_path, exist_ok=True)
plt.savefig(os.path.join(output_path, "invoke_time.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(output_path, "invoke_time.png"), bbox_inches="tight", dpi=300)

if not df_plot.empty:
    print("\n=== Summary ===")
    summary = df_plot.groupby(["System", "Sensors"])["Invoke Time (ms)"].agg(["mean", "std", "median", "count"])
    print(summary.to_string())
