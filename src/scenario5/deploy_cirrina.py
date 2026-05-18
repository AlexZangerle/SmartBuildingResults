import datetime
import json
import logging
import tarfile
import time
from pathlib import Path

import enoslib as en

en.init_logging(level=logging.INFO)

# --- Experiment parameters ---
EXPERIMENT = "s5"
CIRRINA_IMAGE = "collaborativestatemachines/cirrina:unstable"
ETCD_IMAGE = "quay.io/coreos/etcd:v3.5.12"
SERVICE_IMAGE = "alexzangerle/buildingservice-csm-s4:latest"
SIMULATION_IMAGE = "alexzangerle/simulation-csm-s4:latest"
ZENOH_ROUTER_IMAGE = "eclipse/zenoh:1.4.0"
MAIN_URI = "https://raw.githubusercontent.com/AlexZangerle/csmba/refs/heads/main/smartBuilding/main.pkl"
LOCAL_ROOT = Path(f"./results/smartBuilding/{EXPERIMENT}/cirrina")
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
        dest=roles["doorsNear"] + roles["doorsFar"],
        delay="10ms",
        rate="1gbit",
        symmetric=True,
    )
    netem.deploy()

    simulation_addr = roles["simulation"][0].address

    # Zenoh config with endpoint for router
    zenoh_config = json.dumps(
        {
            "mode": "peer",
            "connect": {"endpoints": [f"tcp/{simulation_addr}:7447"]},
            "scouting": {
                "multicast": {"enabled": True},
                "gossip": {"enabled": True},
            },
        }
    )

    with en.actions(roles=roles) as a:
        a.copy(content=zenoh_config, dest="/tmp/zenoh.json5")
        a.file(path="/tmp/metrics", state="directory", mode="0777")

    # Infrastructure on simulation node
    with en.actions(roles=roles["simulation"]) as a:
        a.docker_container(
            name="zenoh-router",
            image=ZENOH_ROUTER_IMAGE,
            network_mode="host",
            state="started",
        )
        a.docker_container(
            name="etcd",
            image=ETCD_IMAGE,
            network_mode="host",
            state="started",
            command=[
                "/usr/local/bin/etcd",
                "--name",
                "s4",
                "--listen-client-urls",
                "http://0.0.0.0:2379",
                "--advertise-client-urls",
                f"http://{simulation_addr}:2379",
            ],
        )

    # Building service + fire detection
    with en.actions(roles=roles["fireDetection"]) as a:
        a.docker_container(
            name="building-service",
            image=SERVICE_IMAGE,
            network_mode="host",
            volumes=["/tmp/metrics:/metrics:rw"],
            state="started",
        )

    # Building service + doorsNear on each door node
    for i, host in enumerate(roles["doorsNear"] + roles["doorsFar"]):
        with en.actions(pattern_hosts=host.address, roles=roles) as a:
            a.docker_container(
                name="building-service",
                image=SERVICE_IMAGE,
                network_mode="host",
                volumes=["/tmp/metrics:/metrics:rw"],
                state="started",
            )

    time.sleep(10)

    # Door runtimes
    for i, host in enumerate(roles["doorsNear"] + roles["doorsFar"]):
        with en.actions(pattern_hosts=host.address, roles=roles) as a:
            a.docker_container(
                name=f"doorsNear{i}",
                image=CIRRINA_IMAGE,
                network_mode="host",
                volumes=[
                    "/tmp/metrics:/metrics:rw",
                    "/tmp/zenoh.json5:/tmp/zenoh.json5:ro",
                ],
                env={
                    "RUN": "0,1,2,3,4",
                    "MAIN_URI": MAIN_URI,
                    "ETCD_CONTEXT_URL": f"http://{simulation_addr}:2379",
                    "ZENOH_EVENT_HANDLER_CONFIG_URI": "/tmp/zenoh.json5",
                },
                state="started",
            )

    # Fire detection
    with en.actions(roles=roles["fireDetection"]) as a:
        a.docker_container(
            name="fire",
            image=CIRRINA_IMAGE,
            network_mode="host",
            volumes=[
                "/tmp/metrics:/metrics:rw",
                "/tmp/zenoh.json5:/tmp/zenoh.json5:ro",
            ],
            env={
                "RUN": "fire",
                "MAIN_URI": MAIN_URI,
                "ETCD_CONTEXT_URL": f"http://{simulation_addr}:2379",
                "ZENOH_EVENT_HANDLER_CONFIG_URI": "/tmp/zenoh.json5",
            },
            state="started",
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
            a.shell("docker start etcd zenoh-router building-service || true")

        with en.actions(roles=roles["simulation"]) as a:
            a.wait_for(port=2379, timeout=30)
            a.wait_for(port=7447, timeout=30)

        # Start all cirrina containers
        with en.actions(roles=roles) as a:
            a.shell("docker start $(docker ps -aq) || true")

        # Start simulation with this sensor count
        with en.actions(roles=roles["simulation"]) as a:
            a.docker_container(
                name="simulation",
                image=SIMULATION_IMAGE,
                network_mode="host",
                volumes=[
                    "/tmp/metrics:/metrics:rw",
                    "/tmp/zenoh.json5:/tmp/zenoh.json5:ro",
                ],
                state="started",
                command=[
                    f"--sensors={sensor_count}",
                    f"--interval={INTERVAL_MS}",
                    f"--duration={DURATION_SEC}",
                    f"--cooldown={COOLDOWN_MS}",
                    "--startup-wait=15",
                    "--metrics=/metrics",
                    "--zenoh-config=/tmp/zenoh.json5",
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
