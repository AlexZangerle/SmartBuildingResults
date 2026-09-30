import os
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Qt5Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

plt.rcParams.update({"font.size": 12})

EXPERIMENT = "s2"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}
START = 300
END = 900

root = Path("results/smartBuilding") / EXPERIMENT

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

fig, ax = plt.subplots(figsize=(8, 5))
if not df_plot.empty:
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
ax.set_title("S2 — Event Latency")
ax.grid(True, linestyle="--", alpha=0.5)
plt.tight_layout()
plt.show()

output_path = f"figure/{EXPERIMENT}"
os.makedirs(output_path, exist_ok=True)
plt.savefig(os.path.join(output_path, "event_latency.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(output_path, "event_latency.png"), bbox_inches="tight", dpi=300)
