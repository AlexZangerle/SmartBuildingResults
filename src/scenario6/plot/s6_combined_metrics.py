import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

plt.rcParams.update({"font.size": 14})

EXPERIMENT = "s6"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}
START = 300
END = 900

root = Path("results/smartBuilding") / EXPERIMENT

# ==========================================
# 1. Load Data for Both Metrics
# ==========================================

# (a) Event Latency Data
latency_records = []
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
            latency_records.append({
                "System": sys_label,
                "Latency (ms)": val,
            })
df_latency = pd.DataFrame(latency_records)

# (b) Invoke Time Data
invoke_records = []
for sys_key, sys_label in systems.items():
    sys_path = root / sys_key
    if not sys_path.exists():
        continue
    for file_path in sys_path.rglob("invoke.time.csv"):
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
                "Invoke Time (ms)": val,
            })
df_invoke = pd.DataFrame(invoke_records)

# ==========================================
# 2. Build 1x2 Subplot Figure (Density Functions)
# ==========================================

fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(15, 3))
axes = axes.flatten()

# Solid line colors and matching transparent fill colors
colors = {"Cirrina": "#33B24C", "Dapr": "#4C4C99"}
fill_colors = {"Cirrina": "#33B24C33", "Dapr": "#4C4C9933"}
labels = list(systems.values())

configs = [
    (df_latency, "Latency (ms)", "(a) Event Latency"),
    (df_invoke, "Invoke Time (ms)", "(b) Service Invoke Time"),
]

for ax, (df, y_col, title) in zip(axes, configs):
    if not df.empty:
        for label in labels:
            vals = df[df["System"] == label][y_col].dropna().values
            if len(vals) > 1:
                kde = gaussian_kde(vals)
                x_vals = np.linspace(vals.min(), vals.max(), 200)
                y_vals = kde(x_vals)

                ax.plot(x_vals, y_vals, label=label, color=colors[label], linewidth=2)
                ax.fill_between(x_vals, y_vals, color=fill_colors[label], alpha=0.5)

        ax.set_xlabel(y_col)
        ax.set_ylabel("Density")
        if (y_col == "Latency (ms)"):
            ax.legend(frameon=True, fancybox=False, edgecolor="gray")
        ax.yaxis.grid(True, linestyle="--", alpha=0.7)
        ax.xaxis.grid(True, linestyle="--", alpha=0.7)
    else:
        ax.text(0.5, 0.5, "No Data Available", ha="center", va="center", transform=ax.transAxes)

plt.tight_layout()

# ==========================================
# 3. Save Figures
# ==========================================

output_path = Path("figure") / EXPERIMENT
output_path.mkdir(parents=True, exist_ok=True)

pdf_file = output_path / "s6_combined_metrics.pdf"
png_file = output_path / "s6_combined_metrics.png"

plt.savefig(pdf_file, bbox_inches="tight")
plt.savefig(png_file, bbox_inches="tight", dpi=300)
plt.close(fig)

print(f"Successfully saved combined 1x2 density subplot figure to:\n - {pdf_file}\n - {png_file}")

# ==========================================
# 4. Print Summaries
# ==========================================

if not df_latency.empty:
    print("\n=== Event Latency Summary ===")
    summary_lat = df_latency.groupby("System")["Latency (ms)"].agg(["mean", "std", "median", "count"])
    print(summary_lat.to_string())

if not df_invoke.empty:
    print("\n=== Invoke Time Summary ===")
    summary_inv = df_invoke.groupby("System")["Invoke Time (ms)"].agg(["mean", "std", "median", "count"])
    print(summary_inv.to_string())