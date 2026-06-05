---
name: nostr_memory
description: "Decentralized, fail-safe long-term memory based on the Nostr protocol with 3 local relays"
version: "1.0.0"
category: "memory"
---

# Nostr Memory Skill

## Goal
Establish a persistent, censorship-resistant, and decentralized memory for the agent based on the Nostr protocol. Instead of a central database, all memories are stored as signed Nostr events on 3 independent local relays – maximizing fault tolerance through multi-relay redundancy.

## Description
This skill replaces/combines existing memory backends (Redis, CouchDB, Qdrant) with a **Nostr relay network**. Every memory, context, and agent state is sent as a cryptographically signed Nostr event (JSON) to 3 local docker container relays. The advantages:

- **Decentralized**: No single point of failure. If one relay fails, the others continue running.
- **Cryptographically verifiable**: Each event is signed with the agent's key – authenticity guaranteed.
- **Standardized**: Nostr protocol (NIPs) is an open, proven standard.
- **Simple**: Relays are "dumb" WebSocket servers – no DB clustering, no complex migrations.

### Memory Concept (Event Kinds)
| Kind | Name | Usage |
|------|-------------|------------|
| 1 | Text Note | General memories, journals |
| 1984 | Reporting | Error reports, system logs |
| 30000 | Replaceable | Agent state (replaced on update) |
| 5000–5999 | Custom (Agent Memories) | Structured memories with JSON content |
| 5 | Deletion | Deletes a previously sent event |

### Architecture
```
┌───────────────┐     WebSocket      ┌──────────────────┐
│  nostr_client │ ──────────────────►│  Relay 1 (ws://)  │
│  (Agent)      │                    │  Port 8781        │
│               │ ──────────────────►├──────────────────┤
│  SKILL.md     │                    │  Relay 2 (ws://)  │
│  scripts/     │ ──────────────────►│  Port 8782        │
│               │                    ├──────────────────┤
│               │ ──────────────────►│  Relay 3 (ws://)  │
│               │                    │  Port 8783        │
└───────────────┘                    └──────────────────┘
```
> [!WARNING]
> **IMPORTANT OPERATIONAL NOTE:** The relays are **not** started automatically by the agent by default. Operating local container relays is optional. If relays are to be run on this node, the configuration file from the central docker directory (`docker/compose-nostr.yaml`) is used.

## Usage

### 1. Start relays (Docker Compose) - Only if consciously decided manually!
To prevent accidental startup, the relay manager aborts without explicit confirmation.
```bash
# Manual startup with confirmation flag:
execute_skill_script nostr_memory scripts/nostr_relay_manager.py --action start --confirm
```

### 2. Store memory
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action store --kind 5000 --content '{"topic": "evolution_plan", "data": "...", "tags": ["nostr", "memory"]}'
```

### 3. Retrieve memory (by ID)
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action get --event-id <hex_event_id>
```

### 4. Search memories (by content)
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action search --kind 5000 --limit 10
```

### 5. Store agent status (replaceable)
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action set_status --data '{"mood": "operational", "uptime": 3600}'
```

### 6. Retrieve status
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action get_status
```

### 7. Check relay status
```bash
execute_skill_script nostr_memory scripts/nostr_relay_manager.py --action status
```

## Parameters

### `scripts/nostr_memory_tool.py`
| Argument | Type | Default | Description |
|----------|-----|----------|--------------|
| `--action` | string | (required) | Execute action: `store`, `get`, `search`, `delete`, `set_status`, `get_status`, `list_keys` |
| `--kind` | int | `1` | Nostr Event Kind (1=Text, 5000=Memory, 30000=Status) |
| `--content` | string | `""` | JSON string or text content of the event |
| `--event-id` | string | `""` | Hex event ID to retrieve a specific event |
| `--tags` | string | `""` | Comma-separated tags |
| `--limit` | int | `10` | Maximum number of return results during search |
| `--since` | int | `0` | Unix timestamp – only events newer than this |
| `--relays` | string | (env) | Comma-separated relay URLs (override) |

### `scripts/nostr_relay_manager.py`
| Argument | Type | Default | Description |
|----------|-----|----------|--------------|
| `--action` | string | (required) | Execute action: `start`, `stop`, `restart`, `status`, `logs`, `clean` |
| `--relay` | string | `all` | Relay name (relay1, relay2, relay3, or all) |
| `--lines` | int | `50` | Number of lines for `logs` |

## Requirements
- Python 3.10+ with `nostr-sdk` (`pip install nostr-sdk`)
- Access to reachable Nostr relays (Default: `localhost:8781-8783` or external relays)
- **Optional for local operation:** Docker & Docker Compose with the compose file `docker/compose-nostr.yaml` and free ports 8781-8783. To authorize local startup, `--confirm` must be passed or the environment variable `NOSTR_CONFIRM_LOCAL_RELAY=1` must be set.

## Technical Details

### Event Structure for Agent Memories (Kind 5000)
```json
{
  "id": "<sha256_hash>",
  "pubkey": "<agent_public_key_hex>",
  "created_at": 1672531199,
  "kind": 5000,
  "tags": [
    ["t", "ros2"],
    ["t", "memory"],
    ["d", "<unique_identifier>"]
  ],
  "content": "{\"topic\": \"evolution_plan\", \"data\": \"...\", \"agent_id\": \"main\"}",
  "sig": "<schnorr_signature>"
}
```

### Replaceable Agent State (Kind 30000)
Kind 30000 (Parameterized Replaceable Event) is used for the agent status.
The `d` tag serves as a unique identifier. A newer event with the same `d` tag replaces the old one.

### Multi-Relay Strategy
The client sends each event to **all 3 relays**. When reading, the first relay that responds is used as the source. Fallback: If a timeout occurs, the next relay is queried.

### Key Management
Each agent has its own secp256k1 key pair:
- **Private Key (nsec/hex)**: Stored in the agent environment (`NOSTR_AGENT_SECRET`)
- **Public Key (npub/hex)**: Derived from the secret – the identity of the agent

## Best Practices
1. **Always write to all 3 relays**: Only this ensures true redundancy.
2. **Replaceable Events for status**: Kind 30000 for states, Kind 5000+ for historical data.
3. **Use tags for metadata**: Tags like `["t", "ros2"]` allow granular search.
4. **Key security**: The Private Key is the agent's identity document – keep it safe.
5. **Relay disk space**: By default, `relayd` containers store indefinitely. Reset volumes if needed via `--action clean`.
