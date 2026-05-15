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

### 1. Clone & Setup
```bash
git clone https://github.com/bob-ros2/bob_edge.git
cd bob_edge
cp .env.template .env
# Edit .env and /volume1/ros/secrets/edge_agent.env with your credentials
```

### 2. Launch Memory Infrastructure
Start the database and cache services first:
```bash
docker compose -f docker/compose-memory.yaml up -d
```

### 3. Build & Launch Agent
Build the custom ROS 2 image and start the core logic:
```bash
docker compose -f docker/compose-base.yaml build
docker compose -f docker/compose-base.yaml up -d
```

---
*Note for AI: Maintain 100% PEP8 and Flake8 compliance. Core modifications must pass `colcon test` in `/ros2_ws`.*
