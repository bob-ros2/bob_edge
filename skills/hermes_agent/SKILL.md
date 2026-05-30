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

To run with a custom system prompt:
```bash
execute_skill_script hermes_agent scripts/run_agent.py "Write a simple program" --system "You are a senior COBOL programmer."
```

To run with YOLO mode disabled (to prompt for confirmation of dangerous commands):
```bash
execute_skill_script hermes_agent scripts/run_agent.py "List files in the current folder" --no-yolo
```

To specify a custom identifier for the output folder name:
```bash
execute_skill_script hermes_agent scripts/run_agent.py "Create a web server" --id web_server_task
```

## Parameters
The script `scripts/run_agent.py` accepts the following arguments:

| Argument | Description | Default |
|---|---|---|
| `prompt` | The task/instruction to run. | *(Required)* |
| `--system` | Custom system prompt (SOUL.md) for the sub-agent. | `None` (uses default) |
| `--model` | Override the default model configured in the environment. | `None` (uses default) |
| `--no-yolo` | Disable YOLO mode, prompting for confirmation before running dangerous commands. | `False` (YOLO is enabled by default) |
| `--id` | Custom identifier suffix for the log directory name. | `subagent` |

### Environment Variables
This skill uses the following environment variables (which can be configured in `.env`):

| Variable | Description | Default Value |
|---|---|---|
| `HERMES_MODEL` | The default LLM model name to run the agent. | `gemma-4-26B-A4B-it-UD` |
| `HERMES_BASE_URL` | The OpenAI-compatible API base URL. | `http://192.168.1.9:8022/v1` |
| `HERMES_API_KEY` | The API token/key for the endpoint. | `dummy_token` |

## Logging & Task History
Each sub-agent execution runs in an isolated temporary profile and writes consolidated results to a persistent task directory:
`~/agent/hermes/task_<YYYYMMDD_HHMMSS>_<identifier>_<random_hex>/`

Inside this folder, the following files are automatically created:
* `run_info.json`: A machine-readable JSON file containing the task metadata (task_id, timestamp, prompt, system_prompt, model, yolo status, and subprocess exit_code).
* `output.log`: The raw output stream (stdout/stderr) of the execution.
* `SOUL.md`: (Optional) The custom system prompt that was applied to the agent.

## Requirements
- `hermes-agent` installed in the container environment.
- The `hermes` CLI executable must be available on the system PATH.
- An active OpenAI-compatible API endpoint (default: `http://192.168.1.9:8022/v1`).

## Technical Details
This skill is a wrapper around the `hermes-agent` CLI.
It sets up isolated, dynamic profiles using `hermes profile create <task_id> --clone`, configures the custom provider dynamically via `~/.hermes/profiles/<task_id>/config.yaml`, writes the system prompt (SOUL.md) if requested, runs the agent, logs the results, and cleans up the profile with `hermes profile delete -y <task_id>` when done.

## Best Practices
- **Isolation**: Each sub-agent runs in the same container environment, so be careful with modifications to files or running persistent background processes.
- **Yolo Mode**: Always run with YOLO mode enabled (default) when invoking the sub-agent programmatically to avoid hanging on interactive prompts.

