import os
from collections import defaultdict
from pathlib import Path

import matplotlib
# Use non-interactive backend for headless execution and saving figures
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

plt.rcParams.update({"font.size": 12})

EXPERIMENT = "s1-electrical"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}
START = 300
END = 900

root = Path("results/smartBuilding") / EXPERIMENT

if not root.exists():
    print(f"Warning: Root directory does not exist: {root.resolve()}")

data = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))

for metrics_path in root.glob("*/*/*/metrics"):
    parts = metrics_path.parts
    sys_key = parts[-4]
    run = parts[-3]
    host = parts[-2]

    if sys_key not in systems:
        continue

    file_path = metrics_path / "event.latency.csv"
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

plot_records = []
for sys_key, sys_label in systems.items():
    if sys_key in data:
        for run in data[sys_key]:
            for host, df in data[sys_key][run].items():
                for val in df["mean"].tolist():
                    plot_records.append({"System": sys_label, "Latency (ms)": val})

df_plot = pd.DataFrame(plot_records)

if df_plot.empty:
    print("Error: No data matched your criteria. Check your file path or CSV column contents.")
else:
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.violinplot(
        data=df_plot, x="System", y="Latency (ms)", hue="System",
        palette="tab10", cut=0, inner="quartile", ax=ax, alpha=0.7, legend=False,
    )
    for i, label in enumerate(systems.values()):
        subset = df_plot[df_plot["System"] == label]["Latency (ms)"]
        if not subset.empty:
            ax.errorbar(i, np.mean(subset), yerr=np.std(subset),
                        fmt="o", color="black", mfc="white", ms=8, capsize=5, zorder=5)

    ax.set_ylabel("Event Latency (ms)")
    ax.set_xlabel("")
    ax.set_title("S1 Electrical — Event Latency")
    ax.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()

    script_dir = Path(__file__).resolve().parent
    output_path = script_dir / "figures"
    output_path.mkdir(parents=True, exist_ok=True)

    pdf_file = output_path / "combined_metrics.pdf"
    png_file = output_path / "combined_metrics.png"

    plt.savefig(pdf_file, bbox_inches="tight")
    plt.savefig(png_file, bbox_inches="tight", dpi=300)
    plt.close(fig)

    print(f"Successfully saved figures to:\n - {pdf_file.resolve()}\n - {png_file.resolve()}")