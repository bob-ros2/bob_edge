#!/usr/bin/env python3
# Copyright 2024 Bob ROS 2
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
"""Plugin-basiertes Live-Dashboard für ROS 2..."""
import asyncio
import importlib
import inspect
import json
import os
import pkgutil
import re
import subprocess
import sys
import threading
import time
from queue import Queue, Empty

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

import bob_edge.plugins

def discover_plugins():
    plugins = []
    for importer, modname, ispkg in pkgutil.iter_modules(bob_edge.plugins.__path__):
        if modname in ("__init__", "base"):
            continue
        try:
            mod = importlib.import_module(f"bob_edge.plugins.{modname}")
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if name != "BasePlugin" and hasattr(obj, "name") and obj.name:
                    instance = obj()
                    plugins.append(instance)
                    print(f"[Plugin] Loaded: {instance.name} ({instance.display_name})")
        except Exception as e:
            print(f"[Plugin] Failed to load {modname}: {e}")
    return plugins


_SECTION_BOUNDARIES = (
    "Subscribers:", "Publishers:",
    "Service Servers:", "Service Clients:",
    "Action Servers:", "Action Clients:",
)

def _safe_id(name):
    sid = re.sub(r'[^a-zA-Z0-9_]', '_', name).strip('_')
    return sid if sid else f"n_{abs(hash(name)) % 10000}"

def _safe_label(label):
    if not label:
        return "topic"
    # Keep only alphanumeric, spaces, dashes, dots, underscores
    label = re.sub(r'[^a-zA-Z0-9_\-\s\.]', '', label).strip()
    return label if label else "topic"

def _node_class(name):
    nl = name.lower()
    if 'dashboard' in nl or 'bridge' in nl or 'ws_' in nl:
        return 'dash'
    if 'chat' in nl:
        return 'tool'
    if 'repl' in nl:
        return 'tool'
    return 'agent'

def _get_llm_model():
    try:
        r = subprocess.run(
            ["ros2", "param", "get", "/agent/agent_brain", "api_model"],
            capture_output=True, text=True, timeout=5.0
        )
        out = r.stdout.strip()
        if 'String value is:' in out:
            return out.split('String value is:')[1].strip()
        return "—"
    except:
        return "—"

def build_mermaid_graph():
    try:
        proc = subprocess.run(["ros2", "node", "list"], capture_output=True, text=True, timeout=5.0)
        nodes = [n.strip() for n in proc.stdout.split('\n') if n.strip()]
        if not nodes:
            return None
        node_pubs, node_subs = {}, {}
        all_topics = set()
        for n in nodes:
            try:
                info = subprocess.run(["ros2", "node", "info", n], capture_output=True, text=True, timeout=3.0)
                pub_topics, sub_topics = set(), set()
                section = None
                for line in info.stdout.split('\n'):
                    s = line.strip()
                    if s in _SECTION_BOUNDARIES:
                        section = {"Subscribers:": "sub", "Publishers:": "pub"}.get(s)
                        continue
                    if section and s.startswith('/'):
                        topic = s.split(':')[0].strip()
                        if topic in ('/parameter_events', '/rosout'):
                            continue
                        all_topics.add(topic)
                        if section == "pub":
                            pub_topics.add(topic)
                        else:
                            sub_topics.add(topic)
                node_pubs[n] = pub_topics
                node_subs[n] = sub_topics
            except:
                node_pubs[n], node_subs[n] = set(), set()
        lines = ["flowchart LR"]
        lines.append('    classDef agent fill:#1f6feb,stroke:#58a6ff,color:#fff;')
        lines.append('    classDef tool fill:#da3633,stroke:#f85149,color:#fff;')
        lines.append('    classDef dash fill:#6e40c9,stroke:#8b5cf6,color:#fff;')
        lines.append('    classDef topic fill:#21262d,stroke:#484f58,color:#8b949e;')
        node_ids = {n: _safe_id(n) for n in nodes}
        relevant = [n for n in nodes if '/' in n]
        for n in relevant:
            lbl = _safe_label(n.split("/")[-1])
            lines.append(f'    {node_ids[n]}["{lbl}"]:::{_node_class(n)}')
        for topic in sorted(all_topics):
            ts = _safe_id(topic)
            tl = _safe_label(topic.split('/')[-1])
            pub_n = [n for n in relevant if topic in node_pubs.get(n, set())]
            sub_n = [n for n in relevant if topic in node_subs.get(n, set())]
            if pub_n and sub_n:
                for pn in pub_n:
                    for sn in sub_n:
                        if pn != sn:
                            lines.append(f'    {node_ids[pn]} -->|{tl}| {node_ids[sn]}')
            elif pub_n:
                lines.append(f'    {ts}(("{tl}")):::topic')
                for pn in pub_n:
                    lines.append(f'    {node_ids[pn]} -->|pub| {ts}')
            elif sub_n:
                lines.append(f'    {ts}(("{tl}")):::topic')
                for sn in sub_n:
                    lines.append(f'    {ts} -->|sub| {node_ids[sn]}')
        return '\n'.join(lines)
    except Exception:
        return None


data_queue: Queue = Queue()
ros_available = False


class DashboardBridgeNode(Node):
    def __init__(self, plugin_list):
        super().__init__("ws_dashboard_bridge")
        self._plugins = plugin_list
        self._pubs = {}
        self._llm_model = _get_llm_model()

        all_topics = set()
        for p in plugin_list:
            for t in p.topics:
                all_topics.add(t)
        for tn in sorted(all_topics):
            self.create_subscription(String, tn, self._cb(tn), 10)
        self.get_logger().info(
            f"DashboardBridge subscribed to {len(all_topics)} topics across {len(plugin_list)} plugins"
        )
        for topic in ["/agent/user_query"]:
            self._pubs[topic] = self.create_publisher(String, topic, 10)

        self._scan_count = 0
        self.create_timer(30.0, self._refresh_model)
        self.create_timer(10.0, self._scan)

    def _refresh_model(self):
        self._llm_model = _get_llm_model()

    def publish_string(self, topic, message):
        if topic in self._pubs:
            m = String(); m.data = message; self._pubs[topic].publish(m)

    def _cb(self, topic_name):
        def cb(msg):
            for p in self._plugins:
                if topic_name in p.topics:
                    try:
                        p.on_ros_msg(topic_name, msg.data, time.time())
                    except Exception as e:
                        self.get_logger().error(f"Plugin {p.name} error: {e}")
            data_queue.put({"plugin": "system", "type": "topic_msg",
                            "data": {"topic": topic_name, "data": msg.data, "ts": time.time()}})
        return cb

    def _scan(self):
        try:
            topic_list = self.get_topic_names_and_types()
            unique_topics = set(t for t, _ in topic_list)
            data_queue.put({
                "plugin": "system", "type": "stats",
                "data": {
                    "nodes": len(self.get_node_names()),
                    "topics": len(unique_topics),
                    "model": self._llm_model,
                }
            })
            self._scan_count += 1
            # Run the expensive subprocess-based Mermaid graph building only once every 10 cycles (100s)
            if self._scan_count % 10 == 1:
                def gen():
                    d = build_mermaid_graph()
                    if d:
                        data_queue.put({"plugin": "system", "type": "mermaid_diagram", "data": d})
                threading.Thread(target=gen, daemon=True).start()
        except Exception:
            pass


app = FastAPI(title="Bob Agent Dashboard")
plugin_list_global = []

HTML_HEAD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bob Agent Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
:root {
  --bg-dark: #0a0e14;
  --bg-panel: #11151c;
  --border: #242b35;
  --text-main: #e2e8f0;
  --text-muted: #8b949e;
  --accent: #58a6ff;
  --accent-hover: #3182ce;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg-dark); 
  color: var(--text-main); display: flex; height: 100vh; overflow: hidden; }

/* Sidebar Navigation */
#sidebar {
  width: 260px;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 24px 16px;
  z-index: 10;
}
.brand {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-main);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 12px;
  letter-spacing: 0.5px;
}
.brand span { color: var(--accent); }
.ws-status {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 32px;
  padding-left: 2px;
  font-weight: 500;
}

.nav-links { display: flex; flex-direction: column; gap: 8px; }
.tab-btn {
  background: transparent;
  color: var(--text-muted);
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 14px;
  font-family: inherit;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  gap: 12px;
}
.tab-btn:hover { background: rgba(255,255,255,0.03); color: var(--text-main); }
.tab-btn.active {
  background: rgba(88, 166, 255, 0.1);
  color: var(--accent);
  border: 1px solid rgba(88, 166, 255, 0.2);
}

/* Main Content Area */
#main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  background: var(--bg-dark);
}
.tab-content {
  display: none;
  width: 100%;
  height: 100%;
  padding: 32px;
  overflow-y: auto;
  animation: fadeIn 0.3s ease;
}
.tab-content.active { display: flex; flex-direction: column; }

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Card overrides for full-page feel */
.card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
  flex: 1;
  display: flex;
  flex-direction: column;
}
.card h2 { color: var(--text-muted); font-size: 13px; text-transform: uppercase; 
  letter-spacing: 1.5px; margin-bottom: 16px; font-weight: 600; }
"""

HTML_TAIL = """</style>
</head>
<body>
<nav id="sidebar">
  <div class="brand">🤖 <span>Bob</span> Agent</div>
  <div id="ws-badge" class="ws-status" style="color: #f85149;">● OFFLINE</div>
  <div class="nav-links">
    TABS_PLACEHOLDER
  </div>
</nav>

<main id="main-content">
  CARDS_PLACEHOLDER
</main>

<script>
mermaid.initialize({ startOnLoad: false, theme: 'dark', fontFamily: 'Inter' });
JS_PLUGINS_PLACEHOLDER

function switchTab(tabId) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('content-' + tabId).classList.add('active');
  document.getElementById('btn-' + tabId).classList.add('active');
}

const ws = new WebSocket("ws://" + location.host + "/ws");
ws.onopen = () => {
    document.getElementById("ws-badge").textContent = "● CONNECTED";
    document.getElementById("ws-badge").style.color = "#3fb950";
};
ws.onclose = () => {
    document.getElementById("ws-badge").textContent = "● OFFLINE";
    document.getElementById("ws-badge").style.color = "#f85149";
};
ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    const plugin = DASHBOARD_PLUGINS[msg.plugin];
    if (plugin && plugin.on_ws_msg) {
        plugin.on_ws_msg(msg);
    }
};
function sendToPlugin(pluginName, type, data) {
    ws.send(JSON.stringify({ plugin: pluginName, type: type, data: data }));
}
</script>
</body>
</html>"""

def build_html(plugin_list):
    js_code = "const DASHBOARD_PLUGINS = {};\n"
    tabs_html, cards_html, css_blocks = "", "", ""
    
    for i, p in enumerate(plugin_list):
        active = "active" if i == 0 else ""
        tabs_html += f'<button id="btn-{p.name}" class="tab-btn {active}" ' \
                     f'onclick="switchTab(\'{p.name}\')">{p.display_name}</button>\n'
        cards_html += f'<div id="content-{p.name}" class="tab-content {active}">{p.html()}</div>\n'
        css_blocks += p.css() + "\n"
        js_code += f"""
(function() {{
    var plugin = {{ {p.js_init()} }};
    plugin.name = "{p.name}";
    DASHBOARD_PLUGINS["{p.name}"] = plugin;
    if (plugin.init) plugin.init();
}})();
"""
    html = HTML_HEAD + css_blocks + HTML_TAIL
    html = html.replace("TABS_PLACEHOLDER", tabs_html)
    html = html.replace("CARDS_PLACEHOLDER", cards_html)
    return html.replace("JS_PLUGINS_PLACEHOLDER", js_code)


@app.get("/")
async def get_index():
    return HTMLResponse(build_html(plugin_list_global))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected = True

    async def read_queue():
        while connected:
            try:
                item = await asyncio.to_thread(data_queue.get, timeout=1.0)
                await websocket.send_json(item)
            except Empty:
                continue
            except Exception:
                break

    async def read_ws():
        nonlocal connected
        while connected:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
                msg = json.loads(raw)
                for p in plugin_list_global:
                    if p.name == msg.get("plugin", ""):
                        p.on_ws_msg(msg); break
            except asyncio.TimeoutError:
                continue
            except Exception:
                connected = False; break

    try:
        await asyncio.gather(read_queue(), read_ws())
    except WebSocketDisconnect:
        connected = False


def ros_spin_thread(plugin_list):
    global ros_available
    try:
        rclpy.init(args=None)
        executor = MultiThreadedExecutor()
        node = DashboardBridgeNode(plugin_list)
        for p in plugin_list:
            p.setup(data_queue, node.publish_string)
        executor.add_node(node)
        ros_available = True
        print("[Dashboard] ROS bridge online")
        try:
            executor.spin()
        finally:
            executor.shutdown()
            node.destroy_node()
            rclpy.shutdown()
    except Exception as e:
        print(f"[Dashboard] ROS bridge failed (Web UI still works): {e}")
        ros_available = False


def main():
    global plugin_list_global
    plugin_list_global = discover_plugins()
    print(f"[Dashboard] Loaded {len(plugin_list_global)} plugins")
    threading.Thread(target=ros_spin_thread, args=(plugin_list_global,), daemon=True).start()
    time.sleep(1.5)
    print("[Dashboard] Starting FastAPI on 0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
