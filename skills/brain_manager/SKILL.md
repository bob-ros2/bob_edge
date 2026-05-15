---
name: brain_manager
description: Discover available LLM models (Chat vs. Reasoning) from environment/.env.
version: 1.3.0
---

# Brain Manager Skill

This skill is the **ONLY** authorized way to discover which LLM models are configured in this environment.

## Tools

### `scripts/brain_tool.py`

Primary discovery tool for LLM configurations.

**Usage:**

```bash
execute_skill_script brain_manager scripts/brain_tool.py
```

**CRITICAL INSTRUCTION**: 
You **MUST** use the path `scripts/brain_tool.py`. Running just `brain_tool.py` will fail.

**What to expect:**
This tool will output a formatted list of available model names. 
- It **DOES NOT** require any YAML config files.
- It **ALREADY KNOWS** how to find the `.env` file.
- **DO NOT** attempt to search for `config.yaml` or `agent_config.yaml` manually.

## Guidelines
1. **Discovery First**: Always run this tool before mentioning model availability.
2. **Copy Model Name**: Use the exact string provided in the `MODEL_NAME` field of the output.
3. **Switching**: Once you have the model name, use the pre-loaded `set_parameter` tool:
   - `set_parameter("/agent/agent_brain", "api_model", "THE_COPIED_MODEL_NAME")`
4. **Cleanup**: Always switch back to the 'chat' model after complex reasoning tasks.
