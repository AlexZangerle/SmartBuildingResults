import os
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

plt.rcParams.update({"font.size": 12})

# Parameters
EXPERIMENT = "s1-gas"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}
files = ["invoke.time.csv"]
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

    for target_file in files:
        file_path = metrics_path / target_file
        if file_path.exists():
            df = pd.read_csv(file_path)
            if df.empty or "t" not in df.columns:
                continue

            # Normalize time to integers (seconds from start)
            df["t"] = (df["t"] - df["t"].iloc[0]).astype(int)

            # Group by time, mean invoke time per second
            df = df.groupby("t")["mean"].mean().to_frame()
            df = df.sort_index()

            # Slice between start and end
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
                    plot_records.append({"System": sys_label, "Invoke Time (ms)": val})

df_plot = pd.DataFrame(plot_records)

# Plotting
fig, ax = plt.subplots(figsize=(8, 5))

if not df_plot.empty:
    sns.violinplot(
        data=df_plot,
        x="System",
        y="Invoke Time (ms)",
        hue="System",
        palette="tab10",
        cut=0,
        inner="quartile",
        ax=ax,
        alpha=0.7,
        legend=False,
    )
    for i, label in enumerate(systems.values()):
        subset = df_plot[df_plot["System"] == label]["Invoke Time (ms)"]
        if not subset.empty:
            mean_val = np.mean(subset)
            std_val = np.std(subset)
            ax.errorbar(
                i, mean_val, yerr=std_val,
                fmt="o", color="black", mfc="white", ms=8, capsize=5, zorder=5,
            )

ax.set_ylabel("Invoke Time (ms)")
ax.set_xlabel("")
ax.set_title("S1 Gas — Service Invoke Time")
ax.grid(True, linestyle="--", alpha=0.5)
plt.tight_layout()

output_path = f"figure/{EXPERIMENT}"
os.makedirs(output_path, exist_ok=True)
plt.savefig(os.path.join(output_path, "invoke_time.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(output_path, "invoke_time.png"), bbox_inches="tight", dpi=300)
#plt.show()
