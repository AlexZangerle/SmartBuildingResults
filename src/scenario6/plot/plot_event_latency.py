import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid", font_scale=1.2)

EXPERIMENT = "s6"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}
START = 300
END = 900

root = Path("results/smartBuilding") / EXPERIMENT

plot_records = []

for sys_key, sys_label in systems.items():
    sys_path = root / sys_key
    if not sys_path.exists():
        continue

    for file_path in sys_path.rglob("event.latency.csv"):
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
                "Latency (ms)": val,
            })

df_plot = pd.DataFrame(plot_records)

fig, ax = plt.subplots(figsize=(8, 5))

if not df_plot.empty:
    palette = {"Cirrina": "#1f77b4", "Dapr": "#ff7f0e"}
    sns.violinplot(
        data=df_plot,
        x="System",
        y="Latency (ms)",
        palette=palette,
        ax=ax,
        inner="quartile",
        cut=0,
    )
    ax.set_xlabel("")
    ax.set_ylabel("Event Latency (ms)")
    ax.grid(True, linestyle="--", alpha=0.4)

plt.tight_layout()

output_path = f"figure/{EXPERIMENT}"
os.makedirs(output_path, exist_ok=True)
plt.savefig(os.path.join(output_path, "event_latency.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(output_path, "event_latency.png"), bbox_inches="tight", dpi=300)

if not df_plot.empty:
    print("\n=== Summary ===")
    summary = df_plot.groupby("System")["Latency (ms)"].agg(["mean", "std", "median", "count"])
    print(summary.to_string())
    above_500 = df_plot[df_plot["Latency (ms)"] > 500]
    print(f"Above 500ms: {len(above_500)} / {len(df_plot)}")
    print(f"Above 1000ms: {len(df_plot[df_plot['Latency (ms)'] > 1000])}")
    print(f"Above 2000ms: {len(df_plot[df_plot['Latency (ms)'] > 2000])}")