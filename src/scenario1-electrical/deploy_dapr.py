import datetime
import logging
import tarfile
import time
from pathlib import Path

import enoslib as en
from tqdm import tqdm

en.init_logging(level=logging.INFO)

# --- Experiment parameters ---
EXPERIMENT = "s1-electrical"
ACTOR_IMAGE = "alexzangerle/smartbuilding-dapr:latest"
REDIS_IMAGE = "redis:8.2.4-alpine"
SIDECAR_IMAGE = "daprio/daprd:1.16.0"
PLACEMENT_IMAGE = "daprio/placement:1.16.0"
SERVICE_IMAGE = "alexzangerle/buildingservice-dapr-s1:latest"
SIMULATION_IMAGE = "alexzangerle/simulation-dapr-s1:latest"
COMPONENTS_PATH = "/tmp/dapr-components"
LOCAL_ROOT = Path(f"./results/smartBuilding/{EXPERIMENT}/dapr")
TIME_BEFORE_FETCH = 60 * 16
NUM_RUNS = 5
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
    .add_machine(roles=["electrical"], cluster="gros", nodes=1)
    .add_machine(roles=["lighting"], cluster="gros", nodes=1)
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
        agent=roles["electrical"] + roles["lighting"] + roles["simulation"],
        bind_var_docker="/tmp/docker",
    )
    d.deploy()

    # Retrieve electrical hostname
    electrical_addr = roles["electrical"][0].address

    Path("config/redis/components").mkdir(parents=True, exist_ok=True)

    # Dynamically create pubsub configuration
    pubsub_yaml = f"""apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: pubsub
spec:
  type: pubsub.redis
  version: v1
  metadata:
    - name: redisHost
      value: "{electrical_addr}:6379"
    - name: redisPassword
      value: ""
    """
    Path("config/redis/components/pubsub.yaml").write_text(pubsub_yaml)

    # Dynamically create statestore configuration
    pubsub_yaml = f"""apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: statestore
spec:
  type: state.redis
  version: v1
  metadata:
    - name: redisHost
      value: "localhost:6379"
    - name: redisPassword
      value: ""
    - name: actorStateStore
      value: "true"
    """
    Path("config/redis/components/statestore.yaml").write_text(pubsub_yaml)

    # Network constraints
    netem = en.NetemHTB()
    netem.add_constraints(
        src=roles["lighting"] + roles["electrical"] + roles["simulation"],
        dest=roles["lighting"] + roles["electrical"] + roles["simulation"],
        delay="10ms",
        rate="1gbit",
        symmetric=True,
    )
    netem.deploy()

    for run_idx in range(1, NUM_RUNS + 1):
        run_label = f"run{run_idx}"
        print(f"\n>>> Starting {run_label}...")

        # Reset metrics directory and push component files
        with en.actions(roles=roles) as a:
            a.file(path="/tmp/metrics", state="absent")
            a.file(path="/tmp/metrics", state="directory", mode="0777")
            a.file(path=COMPONENTS_PATH, state="directory")
            a.copy(src="config/redis/components/", dest=COMPONENTS_PATH + "/")

        # Deploy containers
        with en.actions(roles=roles["simulation"]) as a:
            a.docker_container(
                name="redis", image=REDIS_IMAGE, network_mode="host", state="started"
            )
            a.docker_container(
                name="placement",
                image=PLACEMENT_IMAGE,
                network_mode="host",
                state="started",
                command=["./placement", "--port", "50006"],
            )
            a.docker_container(
                name="simulation-sidecar",
                image=SIDECAR_IMAGE,
                network_mode="host",
                state="started",
                command=[
                    "./daprd",
                    "--app-id",
                    "simulation",
                    "--app-port",
                    "3000",
                    "--resources-path",
                    "/components",
                    "--placement-host-address",
                    "localhost:50006",
                    "--metrics-port",
                    "9091",
                ],
                volumes=[f"{COMPONENTS_PATH}:/components"],
            )

        with en.actions(roles=roles["electrical"]) as a:
            a.docker_container(
                name="building-service", image=SERVICE_IMAGE, network_mode="host", state="started", volumes=["/tmp/metrics:/metrics:rw"],
            )
            a.docker_container(
                name="redis", image=REDIS_IMAGE, network_mode="host", state="started"
            )
            a.docker_container(
                name="placement",
                image=PLACEMENT_IMAGE,
                network_mode="host",
                state="started",
                command=["./placement", "--port", "50006"],
            )
            a.docker_container(
                name="electrical-sidecar",
                image=SIDECAR_IMAGE,
                network_mode="host",
                state="started",
                command=[
                    "./daprd",
                    "--app-id",
                    "electrical-safety",
                    "--app-port",
                    "3000",
                    "--resources-path",
                    "/components",
                    "--placement-host-address",
                    "localhost:50006",
                    "--metrics-port",
                    "9091",
                ],
                volumes=[f"{COMPONENTS_PATH}:/components"],
            )
        
        with en.actions(roles=roles["lighting"]) as a:
            a.docker_container(
                name="building-service", image=SERVICE_IMAGE, network_mode="host", state="started", volumes=["/tmp/metrics:/metrics:rw"],
            )
            a.docker_container(
                name="redis", image=REDIS_IMAGE, network_mode="host", state="started"
            )
            a.docker_container(
                name="placement",
                image=PLACEMENT_IMAGE,
                network_mode="host",
                state="started",
                command=["./placement", "--port", "50006"],
            )
            a.docker_container(
                name="lighting-sidecar",
                image=SIDECAR_IMAGE,
                network_mode="host",
                state="started",
                command=[
                    "./daprd",
                    "--app-id",
                    "lighting",
                    "--app-port",
                    "3000",
                    "--resources-path",
                    "/components",
                    "--placement-host-address",
                    "localhost:50006",
                    "--metrics-port",
                    "9091",
                ],
                volumes=[f"{COMPONENTS_PATH}:/components"],
            )
        time.sleep(10)
        with en.actions(roles=roles["simulation"]) as a:
            a.docker_container(
                name="simulation",
                image=SIMULATION_IMAGE,
                network_mode="host",
                state="started",
                volumes=["/tmp/metrics:/metrics:rw"],
                command=[
                    "--duration=900000", 
                    "--settle=100", 
                    "--metrics=/metrics",
                    "--circuit=electrical",
                    "--dapr-url=http://localhost:3500"
                ],
            )

        with en.actions(roles=roles["lighting"]) as a:
            a.docker_container(
                name="lighting",
                image=ACTOR_IMAGE,
                network_mode="host",
                state="started",
                volumes=["/tmp/metrics:/metrics:rw"],
                env={
                    "ROLE": "lighting",
                    "ACTOR_ID": "lighting-0",
                    "ROOM_ID": "Room 0",
                    "BUILDING_SERVICE_URL": "http://localhost:8005",
                    "DAPR_HTTP_ENDPOINT": "http://localhost:3500",
                    "DAPR_GRPC_ENDPOINT": "http://localhost:50001",
                    "METRICS_DIRECTORY": "/metrics",
                },
            )

        with en.actions(roles=roles["electrical"]) as a:
            a.docker_container(
                name="electrical",
                image=ACTOR_IMAGE,
                network_mode="host",
                state="started",
                volumes=["/tmp/metrics:/metrics:rw"],
                env={
                    "ROLE": "electricalSafety",
                    "ACTOR_ID": "electricalSafety-0",
                    "BUILDING_SERVICE_URL": "http://localhost:8005",
                    "DAPR_HTTP_ENDPOINT": "http://localhost:3500",
                    "DAPR_GRPC_ENDPOINT": "http://localhost:50001",
                    "METRICS_DIRECTORY": "/metrics",
                },
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
