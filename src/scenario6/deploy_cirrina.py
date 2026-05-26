import datetime
import json
import logging
import tarfile
import time
from pathlib import Path

import enoslib as en
from tqdm import tqdm

en.init_logging(level=logging.INFO)

# --- Experiment parameters ---
EXPERIMENT = "s6"
CIRRINA_IMAGE = "collaborativestatemachines/cirrina:unstable"
ETCD_IMAGE = "quay.io/coreos/etcd:v3.5.12"
SERVICE_IMAGE = "alexzangerle/buildingservice-csm-s6:latest"
SIMULATION_IMAGE = "alexzangerle/simulation-csm-s6:latest"
ZENOH_ROUTER_IMAGE = "eclipse/zenoh:1.4.0"
MAIN_URI = "https://raw.githubusercontent.com/AlexZangerle/csmba/refs/heads/main/smartBuilding/main.pkl"
LOCAL_ROOT = Path(f"./results/smartBuilding/{EXPERIMENT}/cirrina")
TIME_BEFORE_FETCH = 60 * 17
NUM_RUNS = 5
START_TIME = None
WALL_TIME = "03:00:00"
# -------------------------------------

# Building-scoped
BUILDING_SCOPED = [
    "buildingSchedule",
    "electricalSafety",
    "energyManagement",
    "fire",
    "gasSafety",
    "securityManager",
]

# Room/door-scoped
ROOM_SCOPED = [
    "hvac",
    "lighting",
    "roomOccupancy",
    "shading",
    "tempSafety",
    "roomSchedule",
    "fireDoor",
    "accessControl",
]

RUN_VALUES = {
    "buildingSchedule": "buildingSchedule",
    "electricalSafety": "electricalSafety",
    "energyManagement": "energyManagement",
    "fire": "fire",
    "gasSafety": "gasSafety",
    "securityManager": "securityManager",
    "hvac": "hvac",
    "lighting": "lighting",
    "roomOccupancy": "roomOccupancy",
    "shading": "shading",
    "tempSafety": "tempSafety",
    "roomSchedule": "roomSchedule",
    "fireDoor": "0",
    "accessControl": "accessControl",
}

# fire hosts infra
INFRA_HOST_ROLE = "fire"

reservation = None
if START_TIME:
    today = datetime.date.today().isoformat()
    reservation = f"{today} {START_TIME}"

conf = en.G5kConf.from_settings(
    job_name=Path(__file__).name, walltime=WALL_TIME, reservation=reservation
)

# Simulation node
conf.add_machine(roles=["simulation"], cluster="paradoxe", nodes=1)

# Building-scoped nodes
for sm in BUILDING_SCOPED:
    conf.add_machine(roles=[sm], cluster="dahu", nodes=1)

# Room-scoped nodes
for sm in ROOM_SCOPED:
    conf.add_machine(roles=[sm], cluster="gros", nodes=1)

provider = en.G5k(conf)

all_sm_roles = BUILDING_SCOPED + ROOM_SCOPED

try:
    roles, networks = provider.init()
    roles = en.sync_info(roles, networks)

    all_sm_hosts = []
    for sm in all_sm_roles:
        all_sm_hosts += roles[sm]
    all_hosts = roles["simulation"] + all_sm_hosts

    # Time sync
    print(">>> Synchronizing Chrony...")
    with en.actions(roles=roles) as a:
        a.apt(name=["chrony"], state="present", update_cache=True)
        a.service(name="chrony", state="started", enabled=True)
        a.shell("chronyc makestep")

    # Docker engine deployment
    registry_opts = dict(type="external", ip="docker-cache.grid5000.fr", port=80)
    d = en.Docker(
        agent=all_hosts,
        bind_var_docker="/tmp/docker",
        registry_opts=registry_opts,
    )
    d.deploy()

    # Network constraints
    infra_addr = roles[INFRA_HOST_ROLE][0].address

    building_hosts = []
    for sm in BUILDING_SCOPED:
        building_hosts += roles[sm]
    room_hosts = []
    for sm in ROOM_SCOPED:
        room_hosts += roles[sm]

    netem = en.NetemHTB()
    netem.add_constraints(
        src=roles["simulation"],
        dest=building_hosts,
        delay="30ms",
        rate="1gbit",
        symmetric=True,
    )
    netem.add_constraints(
        src=roles["simulation"],
        dest=room_hosts,
        delay="10ms",
        rate="1gbit",
        symmetric=True,
    )
    netem.add_constraints(
        src=building_hosts,
        dest=room_hosts,
        delay="20ms",
        rate="1gbit",
        symmetric=True,
    )
    netem.deploy()

    zenoh_config = json.dumps(
        {
            "mode": "peer",
            "connect": {"endpoints": [f"tcp/{infra_addr}:7447"]},
            "scouting": {
                "multicast": {"enabled": True},
                "gossip": {"enabled": True},
            },
        }
    )

    # Distribute zenoh config and create metrics directory on all nodes
    with en.actions(roles=roles) as a:
        a.copy(content=zenoh_config, dest="/tmp/zenoh.json5")
        a.file(path="/tmp/metrics", state="directory", mode="0777")

    for run_idx in range(1, NUM_RUNS + 1):
        run_label = f"run{run_idx}"
        print(f"\n>>> Starting {run_label}...")

        # Reset metrics directory
        with en.actions(roles=roles) as a:
            a.file(path="/tmp/metrics", state="absent")
            a.file(path="/tmp/metrics", state="directory", mode="0777")

        with en.actions(roles=roles[INFRA_HOST_ROLE]) as a:
            a.docker_container(
                name="zenoh-router",
                image=ZENOH_ROUTER_IMAGE,
                network_mode="host",
                state="started",
            )

        with en.actions(roles=roles[INFRA_HOST_ROLE]) as a:
            a.docker_container(
                name="etcd",
                image=ETCD_IMAGE,
                network_mode="host",
                state="started",
                command=[
                    "/usr/local/bin/etcd",
                    "--name",
                    "s6",
                    "--listen-client-urls",
                    "http://0.0.0.0:2379",
                    "--advertise-client-urls",
                    f"http://{infra_addr}:2379",
                ],
            )

        with en.actions(roles=roles[INFRA_HOST_ROLE]) as a:
            a.wait_for(port=2379, timeout=30)
            a.wait_for(port=7447, timeout=30)

        for sm in all_sm_roles:
            with en.actions(roles=roles[sm]) as a:
                a.docker_container(
                    name="building-service",
                    image=SERVICE_IMAGE,
                    network_mode="host",
                    volumes=["/tmp/metrics:/metrics:rw"],
                    state="started",
                )

        time.sleep(10)

        for sm in all_sm_roles:
            with en.actions(roles=roles[sm]) as a:
                a.docker_container(
                    name=sm,
                    image=CIRRINA_IMAGE,
                    network_mode="host",
                    volumes=[
                        "/tmp/metrics:/metrics:rw",
                        "/tmp/zenoh.json5:/tmp/zenoh.json5:ro",
                    ],
                    env={
                        "RUN": RUN_VALUES[sm],
                        "MAIN_URI": MAIN_URI,
                        "ETCD_CONTEXT_URL": f"http://{infra_addr}:2379",
                        "ZENOH_EVENT_HANDLER_CONFIG_URI": "/tmp/zenoh.json5",
                    },
                    state="started",
                )

        with en.actions(roles=roles["simulation"]) as a:
            a.docker_container(
                name="simulation",
                image=SIMULATION_IMAGE,
                network_mode="host",
                volumes=["/tmp/metrics:/metrics:rw"],
                state="started",
                command=[
                    "--duration=900",
                    "--startup-wait=15",
                    "--metrics=/metrics",
                    "--zenoh-config=/tmp/zenoh.json5",
                ],
            )

        # Wait for data collection
        print(f"--- {run_label}: Collecting data for {TIME_BEFORE_FETCH}s ---")
        for _ in tqdm(
                range(TIME_BEFORE_FETCH), desc=run_label, unit="s", mininterval=60
        ):
            time.sleep(1)

        # Stop containers and capture chrony tracking
        print(f"--- {run_label}: Stopping containers and flushing logs ---")
        with en.actions(roles=roles) as a:
            a.shell("docker stop $(docker ps -q) || true")
            a.shell("chronyc tracking > /tmp/metrics/chrony_tracking.txt")
            a.shell("chronyc sources -v > /tmp/metrics/chrony_sources.txt")
            a.shell("tar -czf /tmp/metrics.tar.gz -C /tmp/metrics .")

        # Fetch data
        print(f"--- {run_label}: Fetching data to {LOCAL_ROOT / run_label} ---")
        for host in en.get_hosts(roles):
            host_dir = LOCAL_ROOT / run_label / host.address / "metrics"
            host_dir.mkdir(parents=True, exist_ok=True)
            local_tar = host_dir / "metrics.tar.gz"

            with en.actions(pattern_hosts=host.address, roles=roles) as a:
                a.fetch(src="/tmp/metrics.tar.gz", dest=str(local_tar), flat=True)

            if local_tar.exists():
                with tarfile.open(local_tar, "r:gz") as tar:
                    tar.extractall(path=host_dir)
                local_tar.unlink()

        with en.actions(roles=roles) as a:
            a.shell("docker rm $(docker ps -aq) || true")
            a.file(path="/tmp/metrics", state="absent")
            a.file(path="/tmp/metrics.tar.gz", state="absent")

    print(f"\n--- SUCCESS: Data stored in {LOCAL_ROOT} ---")
finally:
    provider.destroy()