# Copyright 2026 Bob ROS 2
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# flake8: noqa: E501
"""Plugin for displaying active database memory, lists, states, and histories."""

import base64
import json
import os
import threading
import urllib.request

from bob_edge.plugins.base import BasePlugin


class MemoryPlugin(BasePlugin):
    """Plugin to visualize Redis states/histories, CouchDB collections, and Qdrant collections."""

    name = 'memory'
    display_name = 'Memory Manager'
    topics = []  # No direct ROS topics needed; queries DBs directly
    grid_class = 'card full'

    def __init__(self):
        super().__init__()
        self._redis_client = None
        self._connect_redis()

    def _connect_redis(self):
        """Connect to Redis with a ping check."""
        redis_host = os.environ.get('REDIS_HOST', 'agent-redis')
        redis_port = int(os.environ.get('REDIS_PORT', 6379))
        try:
            import redis
            self._redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=0,
                decode_responses=True
            )
            self._redis_client.ping()
        except Exception:
            self._redis_client = None

    def on_ros_msg(self, topic: str, data: str, ts: float):
        """No direct ROS subscriptions needed for database telemetry."""
        pass

    def on_ws_msg(self, msg: dict):
        """Handle incoming WebSocket requests from the frontend."""
        msg_type = msg.get('type')
        if not msg_type:
            return

        if msg_type == 'request_memory_data':
            # Run query in a separate thread to prevent blocking the async loop
            threading.Thread(target=self._fetch_and_send_all_data, daemon=True).start()

        elif msg_type == 'read_redis_key':
            key = msg.get('data', {}).get('key')
            if key:
                threading.Thread(target=self._fetch_and_send_key_data, args=(key,), daemon=True).start()

        elif msg_type == 'read_redis_history_entry':
            category = msg.get('data', {}).get('category')
            index = msg.get('data', {}).get('index', 0)
            if category:
                threading.Thread(target=self._fetch_and_send_history_entry, args=(category, index), daemon=True).start()

    def _fetch_and_send_all_data(self):
        """Fetch status and listings from Redis, CouchDB, and Qdrant, and send update to client."""
        # 1. Redis
        redis_stats = {"online": False}
        redis_keys = []
        if not self._redis_client:
            self._connect_redis()

        if self._redis_client:
            try:
                info = self._redis_client.info()
                redis_stats = {
                    "online": True,
                    "used_memory_human": info.get("used_memory_human", "N/A"),
                    "used_memory_peak_human": info.get("used_memory_peak_human", "N/A"),
                    "connected_clients": info.get("connected_clients", 0),
                    "uptime_days": info.get("uptime_in_days", 0)
                }
                # Retrieve and examine keys
                all_keys = sorted(self._redis_client.keys("*"))
                for k in all_keys:
                    k_type = self._redis_client.type(k)
                    k_len = 0
                    if k_type == "list":
                        k_len = self._redis_client.llen(k)

                    # Determine if it has matching history
                    has_history = False
                    if k.startswith("state:now:"):
                        cat = k.split("state:now:")[-1]
                        history_key = f"state:history:{cat}"
                        has_history = self._redis_client.exists(history_key) == 1

                    redis_keys.append({
                        "key": k,
                        "type": k_type,
                        "len": k_len,
                        "has_history": has_history
                    })
            except Exception as e:
                redis_stats = {"online": False, "error": str(e)}

        # 2. CouchDB
        couchdb_status = {"online": False, "databases": []}
        try:
            couchdb_url = os.environ.get('COUCHDB_URL', 'http://agent-couchdb:5984').rstrip('/')
            couchdb_password = os.environ.get('COUCHDB_PASSWORD', 'agentsecret')
            auth_str = f'admin:{couchdb_password}'
            auth_header = f'Basic {base64.b64encode(auth_str.encode("ascii")).decode("ascii")}'

            req = urllib.request.Request(f"{couchdb_url}/_all_dbs", timeout=2.0)
            req.add_header('Authorization', auth_header)
            with urllib.request.urlopen(req) as response:
                dbs = json.loads(response.read().decode('utf-8'))

            db_details = []
            for db in dbs:
                if db.startswith('_'):
                    continue
                try:
                    req_detail = urllib.request.Request(f"{couchdb_url}/{db}", timeout=1.0)
                    req_detail.add_header('Authorization', auth_header)
                    with urllib.request.urlopen(req_detail) as resp:
                        detail = json.loads(resp.read().decode('utf-8'))
                        db_details.append({
                            "name": db,
                            "doc_count": detail.get("doc_count", 0),
                            "size_bytes": detail.get("sizes", {}).get("file", 0)
                        })
                except Exception:
                    db_details.append({
                        "name": db,
                        "doc_count": -1,
                        "size_bytes": 0
                    })
            couchdb_status = {"online": True, "databases": db_details}
        except Exception as e:
            couchdb_status = {"online": False, "error": str(e), "databases": []}

        # 3. Qdrant
        qdrant_status = {"online": False, "collections": []}
        try:
            qdrant_url = os.environ.get('QDRANT_URL', 'http://agent-qdrant:6333').rstrip('/')
            req = urllib.request.Request(f"{qdrant_url}/collections", timeout=2.0)
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode('utf-8'))
            collections = res.get("result", {}).get("collections", [])

            col_details = []
            for col in collections:
                name = col.get("name")
                try:
                    req_det = urllib.request.Request(f"{qdrant_url}/collections/{name}", timeout=1.0)
                    with urllib.request.urlopen(req_det) as resp:
                        res_det = json.loads(resp.read().decode('utf-8'))
                    result = res_det.get("result", {})
                    col_details.append({
                        "name": name,
                        "status": result.get("status", "unknown"),
                        "vectors_count": result.get("vectors_count", 0),
                        "vector_size": result.get("config", {}).get("params", {}).get("vectors", {}).get("size", "N/A")
                    })
                except Exception:
                    col_details.append({
                        "name": name,
                        "status": "unknown",
                        "vectors_count": -1,
                        "vector_size": "N/A"
                    })
            qdrant_status = {"online": True, "collections": col_details}
        except Exception as e:
            qdrant_status = {"online": False, "error": str(e), "collections": []}

        # Send all data to frontend
        self.send_ws('memory_data_update', {
            "redis": redis_stats,
            "couchdb": couchdb_status,
            "qdrant": qdrant_status,
            "redis_keys": redis_keys
        })

    def _fetch_and_send_key_data(self, key: str):
        """Fetch the details and value of a specific Redis key."""
        if not self._redis_client:
            return

        try:
            k_type = self._redis_client.type(key)
            ttl = self._redis_client.ttl(key)
            val = None
            history_len = 0

            if k_type == 'string':
                val = self._redis_client.get(key)
            elif k_type == 'list':
                history_len = self._redis_client.llen(key)
                # Fetch first element as active/latest
                if history_len > 0:
                    val = self._redis_client.lindex(key, 0)
            else:
                val = f"[Unsupported Type: {k_type}]"

            # Check matching history
            has_history = False
            if key.startswith("state:now:"):
                cat = key.split("state:now:")[-1]
                history_key = f"state:history:{cat}"
                if self._redis_client.exists(history_key) == 1:
                    has_history = True
                    history_len = self._redis_client.llen(history_key)

            self.send_ws('redis_key_data', {
                "key": key,
                "type": k_type,
                "value": val,
                "ttl": ttl,
                "has_history": has_history,
                "history_len": history_len
            })
        except Exception as e:
            self.send_ws('redis_key_data', {
                "key": key,
                "error": str(e)
            })

    def _fetch_and_send_history_entry(self, category: str, index: int):
        """Fetch a specific history entry by index for a given state category."""
        if not self._redis_client:
            return

        history_key = f"state:history:{category}"
        try:
            val = self._redis_client.lindex(history_key, index)
            self.send_ws('redis_history_data', {
                "category": category,
                "index": index,
                "value": val
            })
        except Exception as e:
            self.send_ws('redis_history_data', {
                "category": category,
                "index": index,
                "error": str(e)
            })

    def html(self) -> str:
        """Return HTML layout for the Memory Manager tab."""
        return """
        <div class="memory-container">
            <!-- Database Connection Status Header -->
            <div class="db-status-row">
                <div class="db-badge" id="badge-redis">
                    <div class="badge-header">
                        <span class="dot offline" id="dot-redis"></span>
                        <h4>REDIS STATE DB</h4>
                    </div>
                    <div class="badge-body" id="info-redis">Offline</div>
                </div>
                <div class="db-badge" id="badge-couchdb">
                    <div class="badge-header">
                        <span class="dot offline" id="dot-couchdb"></span>
                        <h4>COUCHDB (JSON)</h4>
                    </div>
                    <div class="badge-body" id="info-couchdb">Offline</div>
                </div>
                <div class="db-badge" id="badge-qdrant">
                    <div class="badge-header">
                        <span class="dot offline" id="dot-qdrant"></span>
                        <h4>QDRANT (VECTOR)</h4>
                    </div>
                    <div class="badge-body" id="info-qdrant">Offline</div>
                </div>
            </div>

            <!-- Workspace: Redis Explorer & Detailed View -->
            <div class="memory-workspace">
                <!-- Left Pane: Redis Key Explorer -->
                <div class="panel explorer-panel">
                    <div class="panel-header">
                        <h3>Redis Explorer</h3>
                        <button class="m-btn small" onclick="sendToPlugin('memory', 'request_memory_data', {})">🔄</button>
                    </div>
                    <input type="text" id="redis-search" placeholder="Filter keys..." oninput="DASHBOARD_PLUGINS.memory.filterKeys()">
                    <div class="keys-tree" id="redis-keys-container">
                        <div class="loading-placeholder">Lade Schlüssel...</div>
                    </div>
                </div>

                <!-- Right Pane: Active Key Inspector -->
                <div class="panel inspector-panel">
                    <div class="panel-header">
                        <h3>Key Inspector</h3>
                        <div id="inspector-actions" style="display:none; gap: 8px;">
                            <button class="m-btn small" id="btn-copy-val" onclick="DASHBOARD_PLUGINS.memory.copyValue()">📋 Copy</button>
                            <button class="m-btn small" id="btn-refresh-val" onclick="DASHBOARD_PLUGINS.memory.refreshCurrentKey()">🔄 Refresh</button>
                        </div>
                    </div>
                    
                    <div class="inspector-body" id="inspector-content">
                        <div class="empty-inspector">
                            <span style="font-size: 32px; margin-bottom: 12px;">🔍</span>
                            <p>Wähle einen Key aus dem Explorer, um dessen Inhalt und Metadaten zu inspizieren.</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Databases Metadata Tables -->
            <div class="collections-workspace">
                <div class="panel table-panel">
                    <div class="panel-header">
                        <h3>CouchDB Collections</h3>
                    </div>
                    <div class="table-container">
                        <table id="couchdb-table">
                            <thead>
                                <tr>
                                    <th>Database Name</th>
                                    <th>Docs Count</th>
                                    <th>File Size</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr><td colspan="3" class="td-placeholder">Lade CouchDB Daten...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="panel table-panel">
                    <div class="panel-header">
                        <h3>Qdrant Collections</h3>
                    </div>
                    <div class="table-container">
                        <table id="qdrant-table">
                            <thead>
                                <tr>
                                    <th>Collection Name</th>
                                    <th>Status</th>
                                    <th>Vectors Count</th>
                                    <th>Dimension</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr><td colspan="4" class="td-placeholder">Lade Qdrant Daten...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Deep Inspect Fullscreen Modal -->
            <div id="inspect-modal" class="m-modal" onclick="DASHBOARD_PLUGINS.memory.closeModal(event)">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3 id="modal-title">Key Detail View</h3>
                        <span class="close-btn" onclick="DASHBOARD_PLUGINS.memory.closeModal(event, true)">&times;</span>
                    </div>
                    <div class="modal-body">
                        <pre><code id="modal-json"></code></pre>
                    </div>
                </div>
            </div>
        </div>
        """

    def css(self) -> str:
        """Return CSS styling for Memory Manager dashboard component."""
        return """
        .memory-container {
            display: flex;
            flex-direction: column;
            gap: 20px;
            height: 100%;
            width: 100%;
        }
        .db-status-row {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
        }
        .db-badge {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 14px 20px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            position: relative;
            overflow: hidden;
        }
        .db-badge::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; height: 2px;
            background: linear-gradient(90deg, var(--accent), #c9d1d9);
            opacity: 0.3;
        }
        .badge-header {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .badge-header h4 {
            font-size: 11px;
            letter-spacing: 1px;
            color: var(--text-muted);
            text-transform: uppercase;
        }
        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
        }
        .dot.online {
            background: #3fb950;
            box-shadow: 0 0 8px rgba(63, 185, 80, 0.5);
        }
        .dot.offline {
            background: #f85149;
            box-shadow: 0 0 8px rgba(248, 81, 73, 0.5);
        }
        .badge-body {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-main);
        }
        .memory-workspace {
            display: grid;
            grid-template-columns: 320px 1fr;
            gap: 16px;
            flex: 1.2;
            min-height: 380px;
        }
        .panel {
            background: rgba(255, 255, 255, 0.01);
            border: 1px solid var(--border);
            border-radius: 12px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .panel-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .panel-header h3 {
            font-size: 13px;
            letter-spacing: 1px;
            text-transform: uppercase;
            color: var(--text-muted);
            margin: 0;
        }
        .explorer-panel {
            padding-bottom: 12px;
        }
        #redis-search {
            margin: 12px 20px;
            background: #0d1117;
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 8px 12px;
            color: var(--text-main);
            font-family: inherit;
            font-size: 13px;
        }
        #redis-search:focus {
            outline: none;
            border-color: var(--accent);
        }
        .keys-tree {
            flex: 1;
            overflow-y: auto;
            padding: 0 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .key-group {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .group-title {
            font-size: 11px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 2px;
            display: flex;
            justify-content: space-between;
        }
        .group-title span.count {
            color: var(--accent);
        }
        .key-item {
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            padding: 8px 10px;
            border-radius: 6px;
            background: rgba(255, 255, 255, 0.01);
            border: 1px solid transparent;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.2s;
        }
        .key-item:hover {
            background: rgba(255, 255, 255, 0.03);
            border-color: var(--border);
        }
        .key-item.selected {
            background: rgba(88, 166, 255, 0.08);
            border-color: rgba(88, 166, 255, 0.3);
            color: var(--accent);
        }
        .key-badge {
            font-size: 9px;
            text-transform: uppercase;
            padding: 2px 6px;
            border-radius: 4px;
            background: #21262d;
            color: var(--text-muted);
        }
        .inspector-panel {
            height: 100%;
        }
        .inspector-body {
            padding: 24px;
            overflow-y: auto;
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .empty-inspector {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-muted);
            text-align: center;
        }
        .inspector-meta-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
        }
        .meta-card {
            background: #0d1117;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .meta-card .label {
            font-size: 11px;
            color: var(--text-muted);
            text-transform: uppercase;
        }
        .meta-card .value {
            font-size: 14px;
            font-weight: 500;
            color: var(--text-main);
        }
        .staleness-indicator {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-weight: 600;
        }
        .staleness-indicator.fresh { color: #3fb950; }
        .staleness-indicator.stale { color: #d29922; }
        .staleness-indicator.dead { color: #f85149; }
        
        .history-controls {
            background: rgba(88, 166, 255, 0.03);
            border: 1px solid rgba(88, 166, 255, 0.15);
            border-radius: 8px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .history-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: var(--text-muted);
        }
        .slider-wrapper {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .history-slider {
            flex: 1;
            -webkit-appearance: none;
            background: #21262d;
            height: 6px;
            border-radius: 3px;
            outline: none;
        }
        .history-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            background: var(--accent);
            cursor: pointer;
            transition: transform 0.1s;
        }
        .history-slider::-webkit-slider-thumb:hover {
            transform: scale(1.2);
        }
        
        .value-viewer-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 200px;
        }
        .viewer-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
            font-size: 12px;
            color: var(--text-muted);
        }
        .value-viewer {
            flex: 1;
            background: #0d1117;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            overflow: auto;
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
            white-space: pre-wrap;
            color: #c9d1d9;
            cursor: pointer;
            transition: border-color 0.2s;
        }
        .value-viewer:hover {
            border-color: rgba(88, 166, 255, 0.4);
        }

        .collections-workspace {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            flex: 0.8;
            min-height: 200px;
        }
        .table-panel {
            padding-bottom: 0;
        }
        .table-container {
            flex: 1;
            overflow-y: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }
        th, td {
            padding: 12px 18px;
            border-bottom: 1px solid var(--border);
        }
        th {
            background: rgba(255, 255, 255, 0.01);
            color: var(--text-muted);
            font-weight: 500;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.5px;
            position: sticky;
            top: 0;
            z-index: 2;
        }
        td {
            color: var(--text-main);
        }
        tr:hover td {
            background: rgba(255, 255, 255, 0.01);
        }
        .td-placeholder {
            text-align: center;
            color: var(--text-muted);
            padding: 30px;
        }
        .loading-placeholder {
            text-align: center;
            color: var(--text-muted);
            padding: 20px 0;
        }

        .m-btn {
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 6px 14px;
            font-size: 12px;
            font-family: inherit;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .m-btn:hover {
            background: #30363d;
            border-color: #8b949e;
            color: #f0f6fc;
        }
        .m-btn.small {
            padding: 4px 10px;
            font-size: 11px;
            border-radius: 4px;
        }

        /* Modal Overlay */
        .m-modal {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.7);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            padding: 40px;
            animation: fadeInModal 0.2s ease;
        }
        @keyframes fadeInModal {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        .modal-content {
            background: var(--bg-panel);
            border: 1px solid var(--border);
            border-radius: 12px;
            max-width: 900px;
            width: 100%;
            max-height: 80vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
        }
        .modal-header {
            padding: 16px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .modal-header h3 {
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin: 0;
        }
        .close-btn {
            font-size: 24px;
            color: var(--text-muted);
            cursor: pointer;
            line-height: 1;
        }
        .close-btn:hover {
            color: var(--text-main);
        }
        .modal-body {
            padding: 24px;
            overflow: auto;
            background: #0d1117;
            border-bottom-left-radius: 11px;
            border-bottom-right-radius: 11px;
            flex: 1;
        }
        .modal-body pre {
            margin: 0;
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
            color: #c9d1d9;
            white-space: pre-wrap;
        }
        """

    def js_init(self) -> str:
        """Return JavaScript client-side logic for interactive keys & DB telemetry."""
        return """
        init: function() {
            var self = this;
            this.redisKeys = [];
            this.selectedKey = null;
            this.selectedHistoryIndex = 0;
            this.currentKeyValue = null;

            // DOM elements cached
            this.redisKeysContainer = document.getElementById("redis-keys-container");
            this.inspectorContent = document.getElementById("inspector-content");
            this.inspectorActions = document.getElementById("inspector-actions");
            this.couchDbBody = document.querySelector("#couchdb-table tbody");
            this.qdrantBody = document.querySelector("#qdrant-table tbody");
            this.modal = document.getElementById("inspect-modal");
            this.modalTitle = document.getElementById("modal-title");
            this.modalJson = document.getElementById("modal-json");

            // Initial data request
            sendToPlugin('memory', 'request_memory_data', {});

            // Polling for fresh keys and database statuses
            setInterval(function() {
                sendToPlugin('memory', 'request_memory_data', {});
                if (self.selectedKey) {
                    self.refreshCurrentKey();
                }
            }, 6000);
        },

        filterKeys: function() {
            var val = document.getElementById("redis-search").value.toLowerCase();
            var items = this.redisKeysContainer.querySelectorAll(".key-item");
            items.forEach(el => {
                var keyName = el.getAttribute("data-key").toLowerCase();
                if (keyName.includes(val)) {
                    el.style.display = "flex";
                } else {
                    el.style.display = "none";
                }
            });
        },

        selectKey: function(keyName) {
            this.selectedKey = keyName;
            this.selectedHistoryIndex = 0;
            
            // Mark selected in UI
            this.redisKeysContainer.querySelectorAll(".key-item").forEach(el => {
                if (el.getAttribute("data-key") === keyName) {
                    el.classList.add("selected");
                } else {
                    el.classList.remove("selected");
                }
            });

            // Show action buttons
            this.inspectorActions.style.display = "flex";

            // Fetch details
            sendToPlugin('memory', 'read_redis_key', { key: keyName });
        },

        refreshCurrentKey: function() {
            if (this.selectedKey) {
                if (this.selectedHistoryIndex === 0) {
                    sendToPlugin('memory', 'read_redis_key', { key: this.selectedKey });
                } else {
                    // Refresh current history entry index
                    var cat = this.selectedKey.split("state:now:")[1];
                    sendToPlugin('memory', 'read_redis_history_entry', { category: cat, index: this.selectedHistoryIndex });
                }
            }
        },

        copyValue: function() {
            if (this.currentKeyValue) {
                navigator.clipboard.writeText(this.currentKeyValue);
                var btn = document.getElementById("btn-copy-val");
                var orig = btn.textContent;
                btn.textContent = "✅ Copied";
                setTimeout(() => { btn.textContent = orig; }, 1500);
            }
        },

        handleHistorySlider: function(val) {
            this.selectedHistoryIndex = parseInt(val);
            var indexValEl = document.getElementById("hist-index-val");
            if (indexValEl) indexValEl.textContent = val;

            if (this.selectedKey && this.selectedKey.startsWith("state:now:")) {
                var cat = this.selectedKey.split("state:now:")[1];
                if (this.selectedHistoryIndex === 0) {
                    // Fetch latest from active key
                    sendToPlugin('memory', 'read_redis_key', { key: this.selectedKey });
                } else {
                    // Fetch history entry index (note: Redis indices in list are 0-based.
                    // Let's match UI index 1 -> LINDEX 0, UI index 2 -> LINDEX 1, etc.)
                    sendToPlugin('memory', 'read_redis_history_entry', { category: cat, index: this.selectedHistoryIndex - 1 });
                }
            }
        },

        stepHistory: function(offset) {
            var slider = document.getElementById("hist-slider-el");
            if (slider) {
                var newVal = parseInt(slider.value) + offset;
                if (newVal >= parseInt(slider.min) && newVal <= parseInt(slider.max)) {
                    slider.value = newVal;
                    this.handleHistorySlider(newVal);
                }
            }
        },

        openModal: function() {
            if (this.currentKeyValue) {
                this.modalTitle.textContent = "Inspection: " + this.selectedKey + 
                    (this.selectedHistoryIndex > 0 ? " (History Entry #" + this.selectedHistoryIndex + ")" : " (Latest State)");
                
                var formatted = this.currentKeyValue;
                try {
                    var parsed = JSON.parse(this.currentKeyValue);
                    formatted = JSON.stringify(parsed, null, 2);
                } catch(e) {}

                this.modalJson.textContent = formatted;
                this.modal.style.display = "flex";
            }
        },

        closeModal: function(evt, force) {
            if (force || evt.target === this.modal) {
                this.modal.style.display = "none";
            }
        },

        calculateStaleness: function(parsedVal) {
            // Check for potential timestamps in parsed value
            var ts = parsedVal.updated_at || parsedVal.timestamp || parsedVal.time || parsedVal.ts;
            if (!ts) return null;
            
            var nowSec = Date.now() / 1000;
            var diff = Math.max(0, nowSec - ts);
            
            if (diff < 5) return { text: "Just Now", class: "fresh" };
            if (diff < 60) return { text: Math.round(diff) + "s ago", class: "fresh" };
            if (diff < 3600) return { text: Math.round(diff / 60) + "m ago", class: "stale" };
            return { text: Math.round(diff / 3600) + "h ago", class: "dead" };
        },

        renderKeyDetails: function(data) {
            this.currentKeyValue = data.value;
            var valStr = data.value || "";
            var isJson = false;
            var formattedVal = valStr;
            var staleness = null;

            try {
                var parsed = JSON.parse(valStr);
                isJson = true;
                formattedVal = JSON.stringify(parsed, null, 2);
                staleness = this.calculateStaleness(parsed);
            } catch(e) {}

            var ttlStr = data.ttl === -1 ? "Never" : (data.ttl + "s");
            
            var stalenessHtml = "";
            if (staleness) {
                stalenessHtml = `
                    <div class="meta-card">
                        <span class="label">Staleness (Age)</span>
                        <span class="value staleness-indicator ${staleness.class}">● ${staleness.text}</span>
                    </div>
                `;
            }

            var historyHtml = "";
            if (data.has_history && data.history_len > 0) {
                // Limit range mapping
                var totalEntries = data.history_len;
                var currentUIIndex = this.selectedHistoryIndex; // 0 means active, 1..N history index
                historyHtml = `
                    <div class="history-controls">
                        <div class="history-row">
                            <span>⏱️ History Navigation</span>
                            <span>Eintrag: <strong id="hist-index-val">${currentUIIndex === 0 ? "Latest State" : "#" + currentUIIndex}</strong> von ${totalEntries}</span>
                        </div>
                        <div class="slider-wrapper">
                            <button class="m-btn small" onclick="DASHBOARD_PLUGINS.memory.stepHistory(-1)">◀</button>
                            <input type="range" class="history-slider" id="hist-slider-el" 
                                   min="0" max="${totalEntries}" value="${currentUIIndex}" 
                                   oninput="DASHBOARD_PLUGINS.memory.handleHistorySlider(this.value)">
                            <button class="m-btn small" onclick="DASHBOARD_PLUGINS.memory.stepHistory(1)">▶</button>
                        </div>
                    </div>
                `;
            }

            this.inspectorContent.innerHTML = `
                <div class="inspector-meta-grid">
                    <div class="meta-card">
                        <span class="label">Key Name</span>
                        <span class="value" style="font-family:monospace; font-size:12px; word-break:break-all;">${data.key}</span>
                    </div>
                    <div class="meta-card">
                        <span class="label">Storage Type</span>
                        <span class="value" style="text-transform:uppercase;">${data.type}</span>
                    </div>
                    <div class="meta-card">
                        <span class="label">TTL / Expiry</span>
                        <span class="value">${ttlStr}</span>
                    </div>
                    ${stalenessHtml}
                </div>

                ${historyHtml}

                <div class="value-viewer-container">
                    <div class="viewer-header">
                        <span>Payload Visualizer</span>
                        <span style="font-size:10px; color:var(--text-muted);">Double click to expand</span>
                    </div>
                    <div class="value-viewer" ondblclick="DASHBOARD_PLUGINS.memory.openModal()">\n${formattedVal}\n</div>
                </div>
            `;
        },

        renderHistoryEntry: function(data) {
            this.currentKeyValue = data.value;
            var valStr = data.value || "";
            var isJson = false;
            var formattedVal = valStr;

            try {
                var parsed = JSON.parse(valStr);
                isJson = true;
                formattedVal = JSON.stringify(parsed, null, 2);
            } catch(e) {}

            var viewer = this.inspectorContent.querySelector(".value-viewer");
            if (viewer) {
                viewer.textContent = "\\n" + formattedVal + "\\n";
            }
        },

        updateKeysList: function(keys) {
            var self = this;
            this.redisKeys = keys;
            if (keys.length === 0) {
                this.redisKeysContainer.innerHTML = '<div class="loading-placeholder">Keine Schlüssel in Redis gefunden.</div>';
                return;
            }

            // Categorize keys
            var states = [];
            var histories = [];
            var scratchpads = [];
            var others = [];

            keys.forEach(k => {
                if (k.key.startsWith("state:now:")) {
                    states.push(k);
                } else if (k.key.startsWith("state:history:")) {
                    histories.push(k);
                } else if (k.key.startsWith("scratchpad:")) {
                    scratchpads.push(k);
                } else {
                    others.push(k);
                }
            });

            var html = "";
            var renderGroup = (title, list) => {
                if (list.length === 0) return "";
                var groupHtml = `
                    <div class="key-group">
                        <div class="group-title">${title} <span class="count">(${list.length})</span></div>
                `;
                list.forEach(k => {
                    var selClass = self.selectedKey === k.key ? "selected" : "";
                    var lenBadge = k.len > 0 ? `<span class="key-badge">${k.len} entries</span>` : `<span class="key-badge">${k.type}</span>`;
                    groupHtml += `
                        <div class="key-item ${selClass}" data-key="${k.key}" onclick="DASHBOARD_PLUGINS.memory.selectKey('${k.key}')">
                            <span class="key-name-lbl" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:200px;">
                                ${k.key.split(":").slice(2).join(":") || k.key}
                            </span>
                            ${lenBadge}
                        </div>
                    `;
                });
                groupHtml += `</div>`;
                return groupHtml;
            };

            html += renderGroup("Active States", states);
            html += renderGroup("State Histories", histories);
            html += renderGroup("Agent Scratchpads", scratchpads);
            html += renderGroup("Other System Keys", others);

            this.redisKeysContainer.innerHTML = html;
            this.filterKeys();
        },

        updateBadges: function(redis, couchdb, qdrant) {
            // Redis
            var rDot = document.getElementById("dot-redis");
            var rInfo = document.getElementById("info-redis");
            if (redis.online) {
                rDot.className = "dot online";
                rInfo.innerHTML = `Online <span style="color:var(--text-muted); font-size:11px;">(Mem: ${redis.used_memory_human}, Clients: ${redis.connected_clients})</span>`;
            } else {
                rDot.className = "dot offline";
                rInfo.textContent = "Offline / Connection Failed";
            }

            // CouchDB
            var cDot = document.getElementById("dot-couchdb");
            var cInfo = document.getElementById("info-couchdb");
            if (couchdb.online) {
                cDot.className = "dot online";
                cInfo.innerHTML = `Online <span style="color:var(--text-muted); font-size:11px;">(${couchdb.databases.length} DBs)</span>`;
            } else {
                cDot.className = "dot offline";
                cInfo.textContent = "Offline / Service Down";
            }

            // Qdrant
            var qDot = document.getElementById("dot-qdrant");
            var qInfo = document.getElementById("info-qdrant");
            if (qdrant.online) {
                qDot.className = "dot online";
                qInfo.innerHTML = `Online <span style="color:var(--text-muted); font-size:11px;">(${qdrant.collections.length} Collections)</span>`;
            } else {
                qDot.className = "dot offline";
                qInfo.textContent = "Offline / Service Down";
            }
        },

        updateCouchTable: function(databases) {
            if (databases.length === 0) {
                this.couchDbBody.innerHTML = '<tr><td colspan="3" class="td-placeholder">Keine CouchDB-Datenbanken gefunden.</td></tr>';
                return;
            }
            var html = "";
            databases.forEach(db => {
                var sizeHuman = (db.size_bytes / (1024 * 1024)).toFixed(2) + " MB";
                var docCount = db.doc_count === -1 ? "Error" : db.doc_count;
                html += `
                    <tr>
                        <td style="font-family:monospace; font-weight:500;">${db.name}</td>
                        <td>${docCount}</td>
                        <td>${sizeHuman}</td>
                    </tr>
                `;
            });
            this.couchDbBody.innerHTML = html;
        },

        updateQdrantTable: function(collections) {
            if (collections.length === 0) {
                this.qdrantBody.innerHTML = '<tr><td colspan="4" class="td-placeholder">Keine Qdrant-Collections gefunden.</td></tr>';
                return;
            }
            var html = "";
            collections.forEach(col => {
                var badgeColor = col.status === "green" ? "#3fb950" : (col.status === "yellow" ? "#d29922" : "#f85149");
                var statusHtml = `<span style="color:${badgeColor}; font-weight:600; text-transform:uppercase; font-size:11px;">${col.status}</span>`;
                var vecCount = col.vectors_count === -1 ? "Error" : col.vectors_count;
                html += `
                    <tr>
                        <td style="font-family:monospace; font-weight:500;">${col.name}</td>
                        <td>${statusHtml}</td>
                        <td>${vecCount}</td>
                        <td>${col.vector_size}</td>
                    </tr>
                `;
            });
            this.qdrantBody.innerHTML = html;
        },

        on_ws_msg: function(msg) {
            if (msg.type === "memory_data_update") {
                this.updateBadges(msg.data.redis, msg.data.couchdb, msg.data.qdrant);
                this.updateKeysList(msg.data.redis_keys);
                this.updateCouchTable(msg.data.couchdb.databases);
                this.updateQdrantTable(msg.data.qdrant.collections);
            } else if (msg.type === "redis_key_data") {
                if (msg.data.key === this.selectedKey) {
                    this.renderKeyDetails(msg.data);
                }
            } else if (msg.type === "redis_history_data") {
                if (this.selectedKey && this.selectedKey.endsWith(":" + msg.data.category)) {
                    this.renderHistoryEntry(msg.data);
                }
            }
        }
        """
