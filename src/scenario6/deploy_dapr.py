import datetime
import logging
import tarfile
import time
from pathlib import Path

import enoslib as en
from tqdm import tqdm

en.init_logging(level=logging.INFO)

# --- Experiment parameters ---
EXPERIMENT = "s6"
ACTOR_IMAGE = "alexzangerle/smartbuilding-dapr:latest"
REDIS_IMAGE = "redis:8.2.4-alpine"
SIDECAR_IMAGE = "daprio/daprd:1.16.0"
PLACEMENT_IMAGE = "daprio/placement:1.16.0"
SERVICE_IMAGE = "alexzangerle/buildingservice-dapr-s6:latest"
SIMULATION_IMAGE = "alexzangerle/simulation-dapr-s6:latest"
COMPONENTS_PATH = "/tmp/dapr-components"
LOCAL_ROOT = Path(f"./results/smartBuilding/{EXPERIMENT}/dapr")
TIME_BEFORE_FETCH = 60 * 15
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

APP_IDS = {
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
    "fireDoor": "fireDoor",
    "accessControl": "accessControl",
}

ACTOR_ROLES = {
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
    "fireDoor": "fireDoor",
    "accessControl": "accessControl",
}

ACTOR_EXTRA_ENV = {
    "buildingSchedule": {"ACTOR_ID": "buildingSchedule-0"},
    "electricalSafety": {"ACTOR_ID": "electricalSafety-0"},
    "energyManagement": {"ACTOR_ID": "energyManagement-0"},
    "fire":             {"ACTOR_ID": "fire-0"},
    "gasSafety":        {"ACTOR_ID": "gasSafety-0"},
    "securityManager":  {"ACTOR_ID": "securityManager-0"},
    "hvac":             {"ACTOR_ID": "hvac-0", "ROOM_ID": "Room 0"},
    "lighting":         {"ACTOR_ID": "lighting-0", "ROOM_ID": "Room 0"},
    "roomOccupancy":    {"ACTOR_ID": "roomOccupancy-0"},
    "shading":          {"ACTOR_ID": "shading-0", "ROOM_ID": "Room 0"},
    "tempSafety":       {"ACTOR_ID": "tempSafety-0", "ROOM_ID": "Room 0"},
    "roomSchedule":     {"ACTOR_ID": "roomSchedule-0", "ROOM_ID": "Room 0"},
    "fireDoor":         {"DOOR_IDS": "0"},
    "accessControl":    {"ACTOR_ID": "accessControl-0", "DOOR_ID": "Door 0"},
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

    infra_addr = roles[INFRA_HOST_ROLE][0].address

    Path("config/redis/components").mkdir(parents=True, exist_ok=True)

    pubsub_yaml = f"""apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: pubsub
spec:
  type: pubsub.redis
  version: v1
  metadata:
    - name: redisHost
      value: "{infra_addr}:6379"
    - name: redisPassword
      value: ""
    """
    Path("config/redis/components/pubsub.yaml").write_text(pubsub_yaml)

    statestore_yaml = """apiVersion: dapr.io/v1alpha1
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
    Path("config/redis/components/statestore.yaml").write_text(statestore_yaml)

    for run_idx in range(1, NUM_RUNS + 1):
        run_label = f"run{run_idx}"
        print(f"\n>>> Starting {run_label}...")

        # Reset metrics and push component files
        with en.actions(roles=roles) as a:
            a.file(path="/tmp/metrics", state="absent")
            a.file(path="/tmp/metrics", state="directory", mode="0777")
            a.file(path=COMPONENTS_PATH, state="directory")
            a.copy(src="config/redis/components/", dest=COMPONENTS_PATH + "/")

        with en.actions(roles=roles[INFRA_HOST_ROLE]) as a:
            a.docker_container(
                name="redis-pubsub",
                image=REDIS_IMAGE,
                network_mode="host",
                state="started",
            )

        for sm in all_sm_roles:
            with en.actions(roles=roles[sm]) as a:
                if sm != INFRA_HOST_ROLE:
                    a.docker_container(
                        name="redis",
                        image=REDIS_IMAGE,
                        network_mode="host",
                        state="started",
                    )
                a.docker_container(
                    name="placement",
                    image=PLACEMENT_IMAGE,
                    network_mode="host",
                    state="started",
                    command=["./placement", "--port", "50006"],
                )
                a.docker_container(
                    name="building-service",
                    image=SERVICE_IMAGE,
                    network_mode="host",
                    state="started",
                    volumes=["/tmp/metrics:/metrics:rw"],
                )

        with en.actions(roles=roles["simulation"]) as a:
            a.docker_container(
                name="redis",
                image=REDIS_IMAGE,
                network_mode="host",
                state="started",
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
                    "--app-id", "simulation",
                    "--app-port", "3000",
                    "--resources-path", "/components",
                    "--placement-host-address", "localhost:50006",
                    "--metrics-port", "9091",
                ],
                volumes=[f"{COMPONENTS_PATH}:/components"],
            )

        for sm in all_sm_roles:
            with en.actions(roles=roles[sm]) as a:
                a.docker_container(
                    name=f"{sm}-sidecar",
                    image=SIDECAR_IMAGE,
                    network_mode="host",
                    state="started",
                    command=[
                        "./daprd",
                        "--app-id", APP_IDS[sm],
                        "--app-port", "3000",
                        "--resources-path", "/components",
                        "--placement-host-address", "localhost:50006",
                        "--metrics-port", "9091",
                    ],
                    volumes=[f"{COMPONENTS_PATH}:/components"],
                )

        time.sleep(10)

        for sm in all_sm_roles:
            env = {
                "ROLE": ACTOR_ROLES[sm],
                "BUILDING_SERVICE_URL": "http://localhost:8005",
                "DAPR_HTTP_ENDPOINT": "http://localhost:3500",
                "DAPR_GRPC_ENDPOINT": "http://localhost:50001",
                "METRICS_DIRECTORY": "/metrics",
            }
            env.update(ACTOR_EXTRA_ENV.get(sm, {}))

            with en.actions(roles=roles[sm]) as a:
                a.docker_container(
                    name=sm,
                    image=ACTOR_IMAGE,
                    network_mode="host",
                    state="started",
                    volumes=["/tmp/metrics:/metrics:rw"],
                    env=env,
                )

        with en.actions(roles=roles["simulation"]) as a:
            a.docker_container(
                name="simulation",
                image=SIMULATION_IMAGE,
                network_mode="host",
                state="started",
                volumes=["/tmp/metrics:/metrics:rw"],
                command=[
                    "--duration=900",
                    "--startup-wait=15",
                    "--metrics=/metrics",
                    f"--dapr-url=http://localhost:3500",
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