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

EXPERIMENT = "s1-electrical"
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}
START = 300
END = 900

root = Path("results/smartBuilding") / EXPERIMENT

plot_records = []

for sys_key, sys_label in systems.items():
    sys_path = root / sys_key
    if not sys_path.exists():
        continue
    for run_dir in sorted(sys_path.glob("run*")):
        all_elec_polls = []
        all_lighting_actions = []

        for host_dir in run_dir.iterdir():
            bs_csv = host_dir / "metrics" / "building_service.csv"
            if not bs_csv.exists():
                continue
            df = pd.read_csv(bs_csv)
            if df.empty or "event_type" not in df.columns:
                continue
            elec = df[df["event_type"] == "elec_poll"]["epoch_ns"].values
            light = df[df["event_type"].isin(["lighting_action", "elec_consumer"])]["epoch_ns"].values
            all_elec_polls.extend(elec)
            all_lighting_actions.extend(light)

        all_elec_polls = np.sort(all_elec_polls)
        all_lighting_actions = np.sort(all_lighting_actions)

        if len(all_elec_polls) == 0 or len(all_lighting_actions) == 0:
            continue

        light_idx = 0
        for poll_ns in all_elec_polls:
            while light_idx < len(all_lighting_actions) and all_lighting_actions[light_idx] < poll_ns:
                light_idx += 1
            if light_idx < len(all_lighting_actions):
                response_ms = (all_lighting_actions[light_idx] - poll_ns) / 1_000_000.0
                rel_sec = (poll_ns - all_elec_polls[0]) / 1_000_000_000.0
                if START <= rel_sec <= END and 0 < response_ms < 10000:
                    plot_records.append({"System": sys_label, "Response Time (ms)": response_ms})

df_plot = pd.DataFrame(plot_records)

fig, ax = plt.subplots(figsize=(8, 5))
if not df_plot.empty:
    sns.violinplot(
        data=df_plot, x="System", y="Response Time (ms)", hue="System",
        palette="tab10", cut=0, inner="quartile", ax=ax, alpha=0.7, legend=False,
    )
    for i, label in enumerate(systems.values()):
        subset = df_plot[df_plot["System"] == label]["Response Time (ms)"]
        if not subset.empty:
            ax.errorbar(i, np.mean(subset), yerr=np.std(subset),
                        fmt="o", color="black", mfc="white", ms=8, capsize=5, zorder=5)

ax.set_ylabel("Response Time (ms)")
ax.set_xlabel("")
ax.set_title("S1 Electrical — Response Time (elec_poll → lighting_action)")
ax.grid(True, linestyle="--", alpha=0.5)
plt.tight_layout()

output_path = f"figure/{EXPERIMENT}"
os.makedirs(output_path, exist_ok=True)
plt.savefig(os.path.join(output_path, "response_time.pdf"), bbox_inches="tight")
plt.savefig(os.path.join(output_path, "response_time.png"), bbox_inches="tight", dpi=300)
