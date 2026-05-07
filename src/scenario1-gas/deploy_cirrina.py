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
EXPERIMENT = "s1-gas"
CIRRINA_IMAGE = "collaborativestatemachines/cirrina:unstable"
ETCD_IMAGE = "quay.io/coreos/etcd:v3.5.12"
SERVICE_IMAGE = "alexzangerle/buildingservice-csm-s1:latest"
SIMULATION_IMAGE = "alexzangerle/simulation-csm-s1:latest"
MAIN_URI = "https://raw.githubusercontent.com/AlexZangerle/csmba/refs/heads/main/smartBuilding/main.pkl"
LOCAL_ROOT = Path(f"./results/smartBuilding/{EXPERIMENT}/cirrina")
TIME_BEFORE_FETCH = 60 * 2
NUM_RUNS = 1
START_TIME = None
WALL_TIME = "03:00:00"
# -------------------------------------

reservation = None
if START_TIME:
    today = datetime.date.today().isoformat()
    reservation = f"{today} {START_TIME}"

conf = (
    en.G5kConf.from_settings(
        job_name=Path(__file__).name, walltime=WALL_TIME, reservation=reservation
    )
    .add_machine(roles=["gas"], cluster="gros", nodes=1)
    .add_machine(roles=["hvac"], cluster="gros", nodes=1)
    .add_machine(roles=["simulation"], cluster="gros", nodes=1)

)

provider = en.G5k(conf)

try:
    roles, networks = provider.init()
    roles = en.sync_info(roles, networks)

    # Time sync
    print(">>> Synchronizing Chrony...")
    with en.actions(roles=roles) as a:
        a.apt(name=["chrony"], state="present", update_cache=True)
        a.service(name="chrony", state="started", enabled=True)
        a.shell("chronyc makestep")

    # Docker engine deployment
    d = en.Docker(
        agent=roles["gas"] + roles["hvac"] + roles["simulation"],
        bind_var_docker="/tmp/docker",
    )
    d.deploy()

    # Network constraints
    netem = en.NetemHTB()
    netem.add_constraints(
        src=roles["gas"] + roles["hvac"] + roles["simulation"],
        dest=roles["gas"] + roles["hvac"] + roles["simulation"],
        delay="10ms",
        rate="1gbit",
        symmetric=True,
    )
    netem.deploy()

    gas_addr = roles["gas"][0].address

    for run_idx in range(1, NUM_RUNS + 1):
        run_label = f"run{run_idx}"
        print(f"\n>>> Starting {run_label}...")

        # Reset metrics directory
        with en.actions(roles=roles) as a:
            a.file(path="/tmp/metrics", state="absent")
            a.file(path="/tmp/metrics", state="directory", mode="0777")


        # Deploy containers
        with en.actions(roles=roles["simulation"]) as a:
            a.docker_container(
                name="simulation",
                image=SIMULATION_IMAGE,
                network_mode="host",
                volumes=["/tmp/metrics:/metrics:rw"],
                state="started",
                command=[
                    "--duration=900000",
                    "--settle=100",
                    "--metrics=/metrics",
                    "--circuit=gas",
                ],
            )

        with en.actions(roles=roles["gas"]) as a:
            a.docker_container(
                name="etcd",
                image=ETCD_IMAGE,
                network_mode="host",
                volumes=["/tmp/metrics:/metrics:rw"],
                state="started",
                command=[
                    "/usr/local/bin/etcd",
                    "--name",
                    "s1",
                    "--listen-client-urls",
                    "http://0.0.0.0:2379",
                    "--advertise-client-urls",
                    f"http://{gas_addr}:2379",
                ],
            )
            a.docker_container(
                name="building-service",
                image=SERVICE_IMAGE,
                network_mode="host",
                volumes=["/tmp/metrics:/metrics:rw"],
                state="started",
            )

        with en.actions(roles=roles["hvac"]) as a:
            a.docker_container(
                name="building-service",
                image=SERVICE_IMAGE,
                network_mode="host",
                volumes=["/tmp/metrics:/metrics:rw"],
                state="started",
            )
        
        time.sleep(10)

        with en.actions(roles=roles["hvac"]) as a:
            a.docker_container(
                name="hvac",
                image=CIRRINA_IMAGE,
                network_mode="host",
                volumes=["/tmp/metrics:/metrics:rw"],
                env={
                    "RUN": "hvac",
                    "MAIN_URI": MAIN_URI,
                    "ETCD_CONTEXT_URL": f"http://{gas_addr}:2379",
                },
                state="started",
            )
        with en.actions(roles=roles["gas"]) as a:
            a.docker_container(
                name="gas",
                image=CIRRINA_IMAGE,
                network_mode="host",
                volumes=["/tmp/metrics:/metrics:rw"],
                env={
                    "RUN": "gasSafety",
                    "MAIN_URI": MAIN_URI,
                    "ETCD_CONTEXT_URL": f"http://{gas_addr}:2379",
                },
                state="started",
            )


        # Wait for data collection
        print(f"--- {run_label}: Collecting data for {TIME_BEFORE_FETCH}s ---")
        for _ in tqdm(
                range(TIME_BEFORE_FETCH), desc=run_label, unit="s", mininterval=60
        ):
            time.sleep(1)

        # Stop containers and capture tracking
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

            with en.actions(roles=roles, pattern_hosts=host.address,) as a:
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
