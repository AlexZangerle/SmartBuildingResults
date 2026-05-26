import datetime
import logging
import tarfile
import time
from pathlib import Path

import enoslib as en

en.init_logging(level=logging.INFO)

# --- Experiment parameters ---
EXPERIMENT = "s5"
ACTOR_IMAGE = "alexzangerle/smartbuilding-dapr:latest"
REDIS_IMAGE = "redis:8.2.4-alpine"
SIDECAR_IMAGE = "daprio/daprd:1.16.0"
PLACEMENT_IMAGE = "daprio/placement:1.16.0"
SERVICE_IMAGE = "alexzangerle/buildingservice-dapr-s4:latest"
SIMULATION_IMAGE = "alexzangerle/simulation-dapr-s4:latest"
COMPONENTS_PATH = "/tmp/dapr-components"
LOCAL_ROOT = Path(f"./results/smartBuilding/{EXPERIMENT}/dapr")
SENSORS = [2, 4, 8, 16, 32, 64]
DURATION_SEC = 60 * 15
COOLDOWN_MS = 5000
INTERVAL_MS = 5000
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
    .add_machine(roles=["simulation"], cluster="paradoxe", nodes=1)
    .add_machine(roles=["fireDetection"], cluster="clervaux", nodes=1)
    .add_machine(roles=["doorsNear"], cluster="gros", nodes=10)
    .add_machine(roles=["doorsFar"], cluster="gros", nodes=10)
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
    registry_opts = dict(type="external", ip="docker-cache.grid5000.fr", port=80)
    d = en.Docker(
        agent=roles["simulation"] + roles["fireDetection"] + roles["doorsNear"] + roles["doorsFar"],
        bind_var_docker="/tmp/docker",
        registry_opts=registry_opts,
    )
    d.deploy()

    # Network constraints
    netem = en.NetemHTB()
    netem.add_constraints(
        src=roles["simulation"],
        dest=roles["fireDetection"],
        delay="30ms",
        rate="1gbit",
        symmetric=True,
    )
    netem.add_constraints(
        src=roles["fireDetection"],
        dest=roles["doorsNear"],
        delay="20ms",
        rate="1gbit",
        symmetric=True,
    )
    netem.add_constraints(
        src=roles["fireDetection"],
        dest=roles["doorsFar"],
        delay="80ms",
        rate="1gbit",
        symmetric=True,
    )
    netem.add_constraints(
        src=roles["simulation"],
        dest=roles["doorsNear"],
        delay="10ms",
        rate="1gbit",
        symmetric=True,
    )

    netem.add_constraints(
        src=roles["simulation"],
        dest=roles["doorsFar"],
        delay="80ms",
        rate="1gbit",
        symmetric=True,
    )

    netem.deploy()

    # Redis is on the simulation node
    simulation_addr = roles["simulation"][0].address

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
      value: "{simulation_addr}:6379"
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

    with en.actions(roles=roles) as a:
        a.file(path="/tmp/metrics", state="directory", mode="0777")
        a.file(path=COMPONENTS_PATH, state="directory")
        a.copy(src="config/redis/components/", dest=COMPONENTS_PATH + "/")

    # Simulation node
    with en.actions(roles=roles["simulation"]) as a:
        a.docker_container(
            name="redis", image=REDIS_IMAGE, network_mode="host", state="started",
        )
        a.docker_container(
            name="placement", image=PLACEMENT_IMAGE, network_mode="host",
            state="started", command=["./placement", "--port", "50006"],
        )
        a.docker_container(
            name="simulation-sidecar", image=SIDECAR_IMAGE, network_mode="host",
            state="started",
            command=[
                "./daprd", "--app-id", "simulation", "--app-port", "3000",
                "--resources-path", "/components",
                "--placement-host-address", "localhost:50006",
                "--metrics-port", "9091",
            ],
            volumes=[f"{COMPONENTS_PATH}:/components"],
        )

    # Fire detection node
    with en.actions(roles=roles["fireDetection"]) as a:
        a.docker_container(
            name="redis", image=REDIS_IMAGE, network_mode="host", state="started",
        )
        a.docker_container(
            name="building-service", image=SERVICE_IMAGE, network_mode="host",
            state="started", volumes=["/tmp/metrics:/metrics:rw"],
        )
        a.docker_container(
            name="placement", image=PLACEMENT_IMAGE, network_mode="host",
            state="started", command=["./placement", "--port", "50006"],
        )
        a.docker_container(
            name="fire-sidecar", image=SIDECAR_IMAGE, network_mode="host",
            state="started",
            command=[
                "./daprd", "--app-id", "fire", "--app-port", "3000",
                "--resources-path", "/components",
                "--placement-host-address", "localhost:50006",
                "--metrics-port", "9091",
            ],
            volumes=[f"{COMPONENTS_PATH}:/components"],
        )

    # Door nodes
    for i, host in enumerate(roles["doorsNear"] + roles["doorsFar"]):
        with en.actions(pattern_hosts=host.address, roles=roles) as a:
            a.docker_container(
                name="redis", image=REDIS_IMAGE, network_mode="host", state="started",
            )
            a.docker_container(
                name="building-service", image=SERVICE_IMAGE, network_mode="host",
                state="started", volumes=["/tmp/metrics:/metrics:rw"],
            )
            a.docker_container(
                name="placement", image=PLACEMENT_IMAGE, network_mode="host",
                state="started", command=["./placement", "--port", "50006"],
            )
            a.docker_container(
                name=f"doorsNear{i}-sidecar", image=SIDECAR_IMAGE, network_mode="host",
                state="started",
                command=[
                    "./daprd", "--app-id", f"doorsNear{i}", "--app-port", "3000",
                    "--resources-path", "/components",
                    "--placement-host-address", "localhost:50006",
                    "--metrics-port", "9091",
                ],
                volumes=[f"{COMPONENTS_PATH}:/components"],
            )

    time.sleep(10)

    # Start door actors
    for i, host in enumerate(roles["doorsNear"] + roles["doorsFar"]):
        with en.actions(pattern_hosts=host.address, roles=roles) as a:
            a.docker_container(
                name=f"doorsNear{i}",
                image=ACTOR_IMAGE,
                network_mode="host",
                state="started",
                volumes=["/tmp/metrics:/metrics:rw"],
                env={
                    "ROLE": "fireDoor",
                    "DOOR_IDS": "0,1,2,3,4",
                    "BUILDING_SERVICE_URL": "http://localhost:8005",
                    "DAPR_HTTP_ENDPOINT": "http://localhost:3500",
                    "DAPR_GRPC_ENDPOINT": "http://localhost:50001",
                    "METRICS_DIRECTORY": "/metrics",
                },
            )

    # Start fire actor
    with en.actions(roles=roles["fireDetection"]) as a:
        a.docker_container(
            name="fire",
            image=ACTOR_IMAGE,
            network_mode="host",
            state="started",
            volumes=["/tmp/metrics:/metrics:rw"],
            env={
                "ROLE": "fire",
                "ACTOR_ID": "fire-0",
                "BUILDING_SERVICE_URL": "http://localhost:8005",
                "DAPR_HTTP_ENDPOINT": "http://localhost:3500",
                "DAPR_GRPC_ENDPOINT": "http://localhost:50001",
                "METRICS_DIRECTORY": "/metrics",
            },
        )

    # Iterate over sensor counts
    for sensor_count in SENSORS:
        print(f"\n>>> Sensors={sensor_count}, Duration={DURATION_SEC}s")

        # Remove old simulation container if exists
        en.run_command(
            "docker rm -f simulation || true",
            roles=roles["simulation"],
        )

        # Clear metrics on all nodes before run
        with en.actions(roles=roles) as a:
            a.shell("rm -rf /tmp/metrics/*")
            a.shell("docker start redis placement building-service || true")

        # Ensure all containers are running
        with en.actions(roles=roles) as a:
            a.shell("docker start $(docker ps -aq) || true")

        # Start simulation with this sensor count
        with en.actions(roles=roles["simulation"]) as a:
            a.docker_container(
                name="simulation",
                image=SIMULATION_IMAGE,
                network_mode="host",
                state="started",
                volumes=["/tmp/metrics:/metrics:rw"],
                command=[
                    f"--sensors={sensor_count}",
                    f"--interval={INTERVAL_MS}",
                    f"--duration={DURATION_SEC}",
                    f"--cooldown={COOLDOWN_MS}",
                    "--startup-wait=15",
                    "--metrics=/metrics",
                    f"--dapr-url=http://localhost:3500",
                ],
            )

        # Wait for simulation to finish
        print(f"--- Waiting for simulation (sensors={sensor_count}) to finish ---")
        en.run_command(
            "docker wait simulation",
            roles=roles["simulation"],
        )

        # Capture chrony tracking and package metrics
        print(f"--- Collecting metrics for sensors={sensor_count} ---")
        with en.actions(roles=roles) as a:
            a.shell("docker stop $(docker ps -q) || true")
            a.shell("chronyc tracking > /tmp/metrics/chrony_tracking.txt")
            a.shell("chronyc sources -v > /tmp/metrics/chrony_sources.txt")
            a.shell("tar -czf /tmp/metrics.tar.gz -C /tmp/metrics .")

        # Fetch data from all nodes
        for host in en.get_hosts(roles):
            host_dir = LOCAL_ROOT / str(sensor_count) / host.address / "metrics"
            host_dir.mkdir(parents=True, exist_ok=True)
            local_tar = host_dir / "metrics.tar.gz"

            with en.actions(pattern_hosts=host.address, roles=roles) as a:
                a.fetch(src="/tmp/metrics.tar.gz", dest=str(local_tar), flat=True)

            if local_tar.exists():
                with tarfile.open(local_tar, "r:gz") as tar:
                    tar.extractall(path=host_dir)
                local_tar.unlink()

        with en.actions(roles=roles) as a:
            a.file(path="/tmp/metrics.tar.gz", state="absent")

        print(f"--- SUCCESS: sensors={sensor_count} data stored in {LOCAL_ROOT / str(sensor_count)} ---")

    # Final cleanup
    print("\n>>> Stopping all containers...")
    with en.actions(roles=roles) as a:
        a.shell("docker rm $(docker ps -aq) || true")
        a.file(path="/tmp/metrics", state="absent")
        a.file(path="/tmp/metrics.tar.gz", state="absent")

    print("\n>>> ALL DONE ---")

finally:
    provider.destroy()
