---
name: hermes_agent
description: "Start autonomous hermes sub-agents to perform tasks and generate responses using configurable local or remote models."
version: "1.0.0"
category: "system"
---

# Hermes Agent Skill

This skill allows the edge agent to spawn autonomous sub-agents using the NousResearch Hermes Agent. It can be used to run complex workflows, code generation tasks, or parallelize execution.

## Goal
To enable dynamic orchestration of sub-agents to execute tasks autonomously.

## Description
The Hermes Agent skill integrates the `hermes-agent` CLI tool as a workspace skill. It reads configuration from the environment (or the central `.env` file) and runs the sub-agent in scripted, non-interactive one-shot mode (`hermes -z`). The sub-agent has access to the local terminal, filesystem, and workspace.

## Usage
Execute a prompt/task using the sub-agent:
```bash
execute_skill_script hermes_agent scripts/run_agent.py "Create a python script that calculates prime numbers up to 100"
```

To override the default model:
```bash
execute_skill_script hermes_agent scripts/run_agent.py "Write a unit test for my node" --model "another-model-name"
```

To run with YOLO mode disabled (to prompt for confirmation of dangerous commands):
```bash
execute_skill_script hermes_agent scripts/run_agent.py "List files in the current folder" --no-yolo
```

## Parameters
The script `scripts/run_agent.py` accepts the following arguments:

| Argument | Description | Default |
|---|---|---|
| `prompt` | The task/instruction to run. | *(Required)* |
| `--model` | Override the default model configured in the environment. | `None` (uses default) |
| `--no-yolo` | Disable YOLO mode, prompting for confirmation before running dangerous commands. | `False` (YOLO is enabled by default) |

### Environment Variables
This skill uses the following environment variables (which can be configured in `.env`):

| Variable | Description | Default Value |
|---|---|---|
| `HERMES_MODEL` | The default LLM model name to run the agent. | `gemma-4-26B-A4B-it-UD` |
| `HERMES_BASE_URL` | The OpenAI-compatible API base URL. | `http://192.168.1.9:8022/v1` |
| `HERMES_API_KEY` | The API token/key for the endpoint. | `dummy_token` |

## Requirements
- `hermes-agent` installed in the container environment.
- The `hermes` CLI executable must be available on the system PATH.
- An active OpenAI-compatible API endpoint (default: `http://192.168.1.9:8022/v1`).

## Technical Details
This skill is a wrapper around the `hermes-agent` CLI.
It sets up the custom provider configuration dynamically via `~/.hermes/config.yaml` using environment variable placeholders. When the `hermes` command runs, it resolves the placeholders using the variables set in the environment or `.env`.

## Best Practices
- **Isolation**: Each sub-agent runs in the same container environment, so be careful with modifications to files or running persistent background processes.
- **Yolo Mode**: Always run with YOLO mode enabled (default) when invoking the sub-agent programmatically to avoid hanging on interactive prompts.
