---
name: memory_manager
description: Interface with short-term (Redis) and long-term (CouchDB, Qdrant) memory components.
version: 1.0.0
---

# Memory Manager Skill

This skill allows agents and sub-agents to persist and retrieve information across the system's memory layers.

## Core Concepts
- **Short-Term (Scratchpad)**: Uses Redis. Volatile, fast working memory. By default, reads/writes are scoped to the current agent's `AGENT_ID`.
- **Long-Term JSON (CouchDB)**: Persistent, structured document storage.
- **Long-Term Vector (Qdrant)**: High-dimensional similarity search for code, context, and concepts.

## Tools

### `scripts/memory_tool.py`

Provides a unified CLI for all memory operations.

#### Scratchpad (Redis)
Store or retrieve short-term data. Automatically uses your `AGENT_ID` as a namespace prefix. You can specify a different `--agent-id` to read another agent's memory.

**Usage:**
```bash
# Write to your scratchpad
execute_skill_script memory_manager scripts/memory_tool.py --action scratchpad_write --data "My thought process..."

# Read your scratchpad
execute_skill_script memory_manager scripts/memory_tool.py --action scratchpad_read

# Read another agent's scratchpad
execute_skill_script memory_manager scripts/memory_tool.py --action scratchpad_read --agent-id subagent_123
```

#### Long-Term JSON (CouchDB)
Store or query structured JSON documents.

**Usage:**
```bash
# Store a document
execute_skill_script memory_manager scripts/memory_tool.py --action couchdb_store --db "knowledge_base" --doc-id "concept_ros_cli" --data '{"topic": "ros", "content": "..."}'

# Fetch a document by ID
execute_skill_script memory_manager scripts/memory_tool.py --action couchdb_fetch --db "knowledge_base" --doc-id "concept_ros_cli"
```

#### Long-Term Vector (Qdrant)
Store or search vector data. *(Note: Embedding generation is currently mocked or requires raw vectors if not using an internal embedding model).*

**Usage:**
```bash
# Query Qdrant (using raw text, assuming the tool handles embedding or uses a proxy)
execute_skill_script memory_manager scripts/memory_tool.py --action qdrant_search --collection "code_snippets" --data "how to use ros param set"
```

#### Shared State & Senses (Redis State Machine)
Access live transient states ("Now" state) or short-term histories for specific agent categories (e.g. YOLOv8 vision detections).

**Usage:**
```bash
# Get the latest vision detections (person, objects, etc.)
execute_skill_script memory_manager scripts/memory_tool.py --action get_state --category vision

# Get the short-term history of vision detections (temporal log)
execute_skill_script memory_manager scripts/memory_tool.py --action get_history --category vision --limit 5
```

## Guidelines
1. **Namespace Isolation**: Always use the scratchpad without `--agent-id` to write to your own workspace. Never overwrite another agent's scratchpad unless explicitly instructed.
2. **Data Structure**: When storing in CouchDB, ensure `--data` is valid JSON.
3. **Persistence**: Use the scratchpad for intermediate thinking. Use CouchDB for finalized, valuable knowledge.
