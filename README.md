# ROS Package [bob_edge](https://github.com/bob-ros2/bob_edge)
[![CI](https://github.com/bob-ros2/bob_edge/actions/workflows/ros2_ci.yml/badge.svg)](https://github.com/bob-ros2/bob_edge/actions/workflows/ros2_ci.yml)
[![amd64](https://img.shields.io/github/actions/workflow/status/bob-ros2/bob_edge/docker.yml?label=amd64&logo=docker)](https://github.com/bob-ros2/bob_edge/actions/workflows/docker.yml)
[![arm64](https://img.shields.io/github/actions/workflow/status/bob-ros2/bob_edge/docker.yml?label=arm64&logo=docker)](https://github.com/bob-ros2/bob_edge/actions/workflows/docker.yml)

Minimalist ROS 2 Edge Agent with autonomous self-evolution capabilities. This package forms the core of an AI assistant operating in a secure, containerized environment.

## Core Concept
`bob_edge` is designed as a technical companion. By leveraging a persistent Python REPL and a dual-layer skill architecture, the agent can:
- **Analyze**: Inspect ROS topologies, logs, and system states.
- **Act**: Execute filesystem operations, semantic searches, and web research.
- **Evolve**: Autonomously develop, test, and deploy new skills in a sandboxed custom directory.

## Security & Architecture
The system follows strict security and portability guidelines:
- **Non-Root Execution**: The agent runs as `rosuser` (UID 1000) inside the container.
- **Read-Only Source**: The core repository mount is strictly Read-Only (`:ro`) to prevent accidental corruption of the base system.
- **Secrets Isolation**: Sensitive credentials (API keys, DB passwords) are decoupled from service configurations and stored in `/volume1/ros/secrets/`.
- **Sandboxed Memory**: The agent has a writable persistent home at `/home/rosuser/agent` for logs, data, and custom skills.

## ROS API

### Nodes

#### 1. `orchestrator`
Central logic unit for query routing and state management.
- **Parameters**:
    - `skill_dir` (string): Comma-separated list of skill paths (e.g., core,custom).
    - `api_url` (string): Endpoint for the LLM backend (proxied via Gateway).
- **Topics**:
    - `Sub: /agent/input` (std_msgs/String): User entry point.
    - `Pub: /agent/llm_stream` (std_msgs/String): Real-time response chunks.

#### 2. `repl`
Persistent Python kernel for executing logic within the agent's context.
- **Topics**:
    - `Sub: /agent/repl/input`: Code for execution.
    - `Pub: /agent/repl/output`: Execution results (stdout/stderr).

## Skills (Unified Skill System)
The agent utilizes a modular skill system based on the Anthropic Agent Skills spec:
- **`core_coder`**: Filesystem access, directory listing, and shell execution.
- **`memory_manager`**: Long-term storage via CouchDB and semantic search via Qdrant.
- **`web_researcher`**: Real-time internet research using SearXNG.
- **`repl_kernel`**: Iterative Python logic execution.

## Dual Skill Loading
Skills are loaded from two distinct locations:
1.  **Core Skills** (`/ros2_ws/src/bob_edge/skills`): Built-in, read-only tools.
2.  **Custom Skills** (`/home/rosuser/agent/skills`): Writable directory where the agent can autonomously save new capabilities.

## Deployment
Use Docker Compose to orchestrate the environment:
- `docker/compose-base.yaml`: Core Agent and API Gateway (Nginx).
- `docker/compose-memory.yaml`: Database services (Redis, CouchDB, Qdrant).

## Quick Start

### 1. Networking (One-Time Setup)
The agent uses a persistent external bridge network to ensure connectivity between memory services, the gateway, and other ROS 2 nodes.
```bash
docker network create agent-net
```

### 2. Configuration
```bash
git clone https://github.com/bob-ros2/bob_edge.git
cd bob_edge
cp .env.template .env
# Important: Update /volume1/ros/secrets/edge_agent.env with your keys!
```

### 3. Production Launch (Multi-Arch: AMD64 & ARM64)
The images are published as multi-arch manifests on GHCR. Docker will automatically pull the correct version for your hardware (e.g., Raspberry Pi or Dev-PC).

**Pull the latest pre-built images:**
```bash
docker compose -f docker/compose-memory.yaml pull
docker compose -f docker/compose-base.yaml pull
```

**Start without local build:**
```bash
docker compose -f docker/compose-memory.yaml up -d
docker compose -f docker/compose-base.yaml up -d --no-build
```

### 5. Interaction (Chat CLI)
To talk to the agent, you can use the built-in chat client from the `bob_llm` package.

**Enter the running container:**
```bash
docker exec -it agent-edge bash
```

**Launch the Chat Client:**
```bash
ros2 run bob_llm chat \
  --topic_in /agent/user_query \
  --topic_out /agent/llm_stream \
  --topic_response /agent/logic/internal/full_response_text \
  --topic_tools /agent/llm_tool_calls \
  --topic_reasoning /agent/llm_reasoning \
  --panels
```

### 6. Live Dashboard (WebSocket)
The agent now includes a real-time visualization dashboard accessible via browser.

**Start the Dashboard (inside container):**
```bash
python3 /home/rosuser/agent/skills/ws_dashboard/scripts/ws_dashboard.py
```
**Access in Browser:**
Navigate to `http://<YOUR_IP>:8000`

### 7. Remote ROS 2 Connection via Zenoh (zenoh-bridge-ros2dds)
To connect two isolated ROS 2 environments (e.g., an edge device and a local dev PC) across different networks or Docker environments, use the dedicated ROS 2 Zenoh bridge (`zenoh-bridge-ros2dds`). This bridge natively understands ROS 2 discovery and correctly maps the Node graph.

*Important:* Both sides must use the same `ROS_DISTRO` variable (e.g., `humble`) to ensure compatible DDS GID lengths (24-byte in Humble vs 16-byte in Iron+).

**1. On the Edge Device (e.g., Raspberry Pi):**
Start the bridge, forcing it to listen on a fixed port (`7447`):
```bash
docker run -d --name agent-zenoh-bridge \
  --network agent-net \
  -p 7447:7447/tcp \
  -e ROS_DOMAIN_ID=55 \
  -e ROS_DISTRO=humble \
  eclipse/zenoh-bridge-ros2dds:latest --listen tcp/0.0.0.0:7447
```

**2. On the Local PC (Development Machine):**
Start a local bridge instance connecting to the edge device:
```bash
docker run -d --name zenoh-bridge-local \
  --net=host \
  -e ROS_DOMAIN_ID=55 \
  -e ROS_DISTRO=humble \
  eclipse/zenoh-bridge-ros2dds:latest --connect tcp/<PI_IP_OR_HOSTNAME>:7447
```

*Note:* After connecting, you may need to reset the local ROS 2 daemon (`ros2 daemon stop`) so tools like `rqt_graph` or `ros2 node list` can refresh their node caches.

---
*Note for AI: Maintain 100% PEP8 and Flake8 compliance. Core modifications must pass `colcon test` in `/ros2_ws`.*
