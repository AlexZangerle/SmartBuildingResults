from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams.update({"font.size": 16})


# --- Configuration ---
systems = {"cirrina": "Cirrina", "dapr": "Dapr"}

parts_count = 1000
arrival_rates_per_sec = [0.25, 1, 10, 100, 1000, 5000]
components = ["arm", "assemblycontroller", "belt", "monitor"]

window = 1800
runs = 5

root = Path("results/smartfactory")
cmap = plt.get_cmap("Set1")

output_path = Path("figure/smartfactory")
output_path.mkdir(parents=True, exist_ok=True)

component_labels = {
    "arm": "Arm",
    "assemblycontroller": "Assembly Controller",
    "belt": "Belt",
    "monitor": "Monitor",
}


# --- 1. Data Collection ---
data_tp = defaultdict(lambda: defaultdict(list))
data_arrival_rate = defaultdict(lambda: defaultdict(list))

data_lat = defaultdict(
    lambda: defaultdict(lambda: defaultdict(list))
)

data_proc = defaultdict(
    lambda: defaultdict(lambda: defaultdict(list))
)

for sys_key in systems:
    for arrival_rate_idx in range(len(arrival_rates_per_sec)):
        for run in range(runs):
            run_id = arrival_rate_idx * runs + run + 1

            production_file = (
                root
                / sys_key
                / f"AR{arrival_rate_idx}"
                / f"RUN{run}"
                / "collector"
                / "metrics"
                / f"ProductionTimes_run_{run_id}.csv"
            )

            arrival_file = (
                root
                / sys_key
                / f"AR{arrival_rate_idx}"
                / f"RUN{run}"
                / "collector"
                / "metrics"
                / "arrival.csv"
            )

            df_run = pd.read_csv(production_file)

            run_start = df_run["start_time_ns"].iloc[0] / 1e9
            run_end = df_run["end_time_ns"].iloc[0] / 1e9

            throughput = parts_count / df_run["completion_time_s"].iloc[0]

            data_tp[sys_key][arrival_rate_idx].append(throughput)

            df = pd.read_csv(arrival_file)

            arrival_rate = df["arrival_rate_per_s"].iloc[0]
            data_arrival_rate[sys_key][arrival_rate_idx].append(arrival_rate)

            for component in components:
                # Event Latency
                latency_file = (
                    root
                    / sys_key
                    / f"AR{arrival_rate_idx}"
                    / f"RUN{run}"
                    / component
                    / "metrics"
                    / "event.latency.csv"
                )

                df = pd.read_csv(latency_file)

                # Restrict measurements to the actual experiment workload
                df = df[
                    (df["t"] >= run_start)
                    & (df["t"] <= run_end)
                ].copy()

                # Group measurements by experiment-relative second
                df["t"] = (df["t"] - run_start).astype(int)

                df = df[
                    df["t"] >= (df["t"].iloc[-1] - window)
                ]

                df = (
                    df.groupby("t")["mean"]
                    .mean()
                    .reset_index()
                )

                df = df[df["mean"] > 0].dropna()

                if not df.empty:
                    data_lat[component][sys_key][
                        arrival_rate_idx
                    ].extend(df["mean"].tolist())

                # Event Processing Time
                processing_file = (
                    root
                    / sys_key
                    / f"AR{arrival_rate_idx}"
                    / f"RUN{run}"
                    / component
                    / "metrics"
                    / "processEvent.time.csv"
                )

                df = pd.read_csv(processing_file)

                # Restrict measurements to the actual experiment workload
                df = df[
                    (df["t"] >= run_start)
                    & (df["t"] <= run_end)
                ].copy()

                # Group measurements by experiment-relative second
                df["t"] = (df["t"] - run_start).astype(int)

                df = df[
                    df["t"] >= (df["t"].iloc[-1] - window)
                ]

                df = (
                    df.groupby("t")["mean"]
                    .mean()
                    .reset_index()
                )

                df = df[df["mean"] > 0].dropna()

                if not df.empty:
                    data_proc[component][sys_key][
                        arrival_rate_idx
                    ].extend(df["mean"].tolist())


# --- 2. Data Aggregation ---
mean_tp = defaultdict(list)
std_tp = defaultdict(list)
mean_arrival_rate = defaultdict(list)

mean_lat = defaultdict(lambda: defaultdict(list))
std_lat = defaultdict(lambda: defaultdict(list))

mean_proc = defaultdict(lambda: defaultdict(list))
std_proc = defaultdict(lambda: defaultdict(list))

for sys_key in systems:
    for arrival_rate_idx in range(len(arrival_rates_per_sec)):
        mean_tp[sys_key].append(
            np.mean(data_tp[sys_key][arrival_rate_idx])
        )

        std_tp[sys_key].append(
            np.std(data_tp[sys_key][arrival_rate_idx])
        )

        mean_arrival_rate[sys_key].append(
            np.mean(data_arrival_rate[sys_key][arrival_rate_idx])
        )

        for component in components:
            latency_values = data_lat[component][sys_key][arrival_rate_idx]
            processing_values = data_proc[component][sys_key][arrival_rate_idx]

            mean_lat[component][sys_key].append(
                np.mean(latency_values)
                if latency_values
                else np.nan
            )

            std_lat[component][sys_key].append(
                np.std(latency_values)
                if latency_values
                else np.nan
            )

            mean_proc[component][sys_key].append(
                np.mean(processing_values)
                if processing_values
                else np.nan
            )

            std_proc[component][sys_key].append(
                np.std(processing_values)
                if processing_values
                else np.nan
            )


# --- 3. Throughput Scalability Plot ---
fig, ax = plt.subplots(figsize=(7, 5))

for i, (sys_key, sys_label) in enumerate(systems.items()):
    ax.errorbar(
        mean_arrival_rate[sys_key],
        mean_tp[sys_key],
        yerr=std_tp[sys_key],
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

ax.set_xscale("log")

ax.set_xlabel("Part Arrival Rate (parts/s)")
ax.set_ylabel("Part Assembly Throughput (parts/s)")

ax.grid(
    True,
    which="major",
    linestyle="--",
    alpha=0.3,
)

ax.set_axisbelow(True)

ax.legend(
    frameon=False,
)

plt.tight_layout()

plt.savefig(
    output_path / "part_assembly_throughput_scalability.pdf",
    bbox_inches="tight",
    dpi=300,
)

plt.savefig(
    output_path / "part_assembly_throughput_scalability.png",
    bbox_inches="tight",
    dpi=300,
)

plt.show()


# --- 4. Event Latency & Processing Time Scalability Plot ---
fig, axes = plt.subplots(
    2,
    len(components),
    figsize=(16, 8),
    sharex=False,
    sharey=False,
)

for component_idx, component in enumerate(components):
    ax_lat = axes[0, component_idx]
    ax_proc = axes[1, component_idx]

    for sys_idx, (sys_key, sys_label) in enumerate(systems.items()):
        # Event Latency
        ax_lat.errorbar(
            mean_arrival_rate[sys_key],
            mean_lat[component][sys_key],
            yerr=std_lat[component][sys_key],
            marker="o",
            linewidth=2,
            markersize=6,
            capsize=5,
            elinewidth=1.5,
            capthick=1.5,
            color=cmap(sys_idx),
            alpha=0.7 if sys_idx == 0 else 1.0,
            label=sys_label,
        )

        # Event Processing Time
        ax_proc.errorbar(
            mean_arrival_rate[sys_key],
            mean_proc[component][sys_key],
            yerr=std_proc[component][sys_key],
            marker="o",
            linewidth=2,
            markersize=6,
            capsize=5,
            elinewidth=1.5,
            capthick=1.5,
            color=cmap(sys_idx),
            alpha=0.7 if sys_idx == 0 else 1.0,
            label=sys_label,
        )

    ax_lat.set_title(component_labels[component])

    ax_lat.set_xscale("log")
    ax_proc.set_xscale("log")

    ax_lat.grid(
        True,
        which="major",
        linestyle="--",
        alpha=0.3,
    )

    ax_proc.grid(
        True,
        which="major",
        linestyle="--",
        alpha=0.3,
    )

    ax_lat.set_axisbelow(True)
    ax_proc.set_axisbelow(True)

    ax_lat.tick_params(
        axis="x",
        labelbottom=False,
    )

    ax_proc.set_xlabel(
        "Part Arrival Rate (parts/s)"
    )

# Y-axis labels only on the first column
axes[0, 0].set_ylabel(
    "Event Latency (ms)"
)

axes[1, 0].set_ylabel(
    "Event Processing Time (ms)"
)

# Legend only in the first subplot
axes[0, 0].legend(
    frameon=False,
    loc="best",
)

fig.subplots_adjust(
    left=0.08,
    right=0.99,
    top=0.92,
    bottom=0.10,
    wspace=0.35,
    hspace=0.20,
)

plt.savefig(
    output_path / "event_latency_processing_time_scalability.pdf",
    bbox_inches="tight",
    dpi=300,
)

plt.savefig(
    output_path / "event_latency_processing_time_scalability.png",
    bbox_inches="tight",
    dpi=300,
)

plt.show()


# --- 5. Final Table Output ---
throughput_summary_records = []
latency_summary_records = []
processing_summary_records = []

for sys_key, sys_label in systems.items():
    for arrival_rate_idx in range(len(arrival_rates_per_sec)):
        throughput_summary_records.append(
            {
                "System": sys_label,
                "Configured Arrival Rate": (
                    arrival_rates_per_sec[arrival_rate_idx]
                ),
                "Observed Arrival Rate": (
                    mean_arrival_rate[sys_key][arrival_rate_idx]
                ),
                "Throughput Mean": (
                    mean_tp[sys_key][arrival_rate_idx]
                ),
                "Throughput Std": (
                    std_tp[sys_key][arrival_rate_idx]
                ),
            }
        )

        for component in components:
            latency_summary_records.append(
                {
                    "Component": component,
                    "System": sys_label,
                    "Configured Arrival Rate": (
                        arrival_rates_per_sec[arrival_rate_idx]
                    ),
                    "Observed Arrival Rate": (
                        mean_arrival_rate[sys_key][arrival_rate_idx]
                    ),
                    "Latency Mean": (
                        mean_lat[component][sys_key][arrival_rate_idx]
                    ),
                    "Latency Std": (
                        std_lat[component][sys_key][arrival_rate_idx]
                    ),
                }
            )

            processing_summary_records.append(
                {
                    "Component": component,
                    "System": sys_label,
                    "Configured Arrival Rate": (
                        arrival_rates_per_sec[arrival_rate_idx]
                    ),
                    "Observed Arrival Rate": (
                        mean_arrival_rate[sys_key][arrival_rate_idx]
                    ),
                    "Processing Time Mean": (
                        mean_proc[component][sys_key][arrival_rate_idx]
                    ),
                    "Processing Time Std": (
                        std_proc[component][sys_key][arrival_rate_idx]
                    ),
                }
            )

df_throughput_summary = pd.DataFrame(
    throughput_summary_records
)

df_latency_summary = pd.DataFrame(
    latency_summary_records
)

df_processing_summary = pd.DataFrame(
    processing_summary_records
)

print("\n--- Throughput Scalability ---")
print(
    df_throughput_summary.to_string(index=False)
)

print("\n--- Event Latency Scalability ---")
print(
    df_latency_summary.to_string(index=False)
)

print("\n--- Event Processing Time Scalability ---")
print(
    df_processing_summary.to_string(index=False)
)