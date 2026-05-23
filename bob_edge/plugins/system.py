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

"""Core system plugin with header status bar, graph, and log..."""


from bob_edge.plugins.base import BasePlugin


class SystemPlugin(BasePlugin):
    name = 'system'
    display_name = 'System Status'
    topics = [
        '/agent/llm_stream',
        '/agent/llm_reasoning',
        '/agent/llm_tool_calls',
        '/agent/user_query',
        '/agent/logic/internal/specialist_response',
        '/agent/logic/internal/full_response_text',
        '/agent/internal/status',
        '/agent/repl/status',
        '/agent/agent_brain/internal/agent_stream',
    ]
    grid_class = 'card'

    def __init__(self):
        super().__init__()
        self._llm_model = '\u2014'

    def on_ros_msg(self, topic: str, data: str, ts: float):
        # Busy on stream activity
        if topic in ('/agent/agent_brain/internal/agent_stream', '/agent/llm_stream'):
            if data.strip():
                self.send_ws('busy', {'busy': True})

        # Idle on response done
        if topic == '/agent/logic/internal/full_response_text':
            self.send_ws('busy', {'busy': False})

        # Sync busy state with orchestrator status heartbeat
        if topic == '/agent/internal/status':
            try:
                import json
                status_dict = json.loads(data)
                if 'Orchestrator' in status_dict:
                    state = status_dict['Orchestrator'].get('State', 'IDLE')
                    self.send_ws('busy', {'busy': (state == 'BUSY')})
            except Exception:
                pass

    def html(self):
        return """
        <div class="card full" id="plugin-system-graph">
            <h2>Node-Graph <span style="color:#484f58;font-size:11px;font-weight:400;">
                (live, every 8s)</span></h2>
            <div class="mermaid" id="mermaid-graph"></div>
        </div>
        <div class="card full" id="plugin-system-log">
            <h2>Live Log</h2>
            <div id="log-container"></div>
        </div>
        """

    def css(self):
        return """
        #header-stats { display: flex; flex-direction: column; gap: 8px;
            font-size: 12px; margin-top: 16px; padding-top: 16px;
            border-top: 1px solid #242b35; }
        #header-stats .stat { display: flex; align-items: center; gap: 8px; }
        #header-stats .stat-label { color: #8b949e; }
        #header-stats .stat-value { color: #f0f6fc; font-weight: 500; }
        .status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }
        .status-dot.idle { background: #3fb950; }
        .status-dot.busy { background: #d29922; animation: pulse 1s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        #topic-count, #node-count { min-width: 18px; display: inline-block; text-align: center; }
        #log-container { max-height: 250px; overflow-y: auto; font-size: 12px;
            font-family: 'JetBrains Mono', monospace; }
        .log-entry { padding: 2px 0; border-bottom: 1px solid #21262d; color: #8b949e; }
        .log-entry .ts { color: #484f58; }
        .log-entry .topic { color: #58a6ff; }
        .log-entry .data { color: #c9d1d9; }
        #mermaid-graph { background: #0d1117; border-radius: 6px; min-height: 180px; }
        """

    def js_init(self):
        return """
        init: function() {
            var self = this;
            this.startTime = Date.now() / 1000;
            this.logEl = document.getElementById('log-container');
            this.maxLogLines = 80;
            this.mermaidEl = document.getElementById('mermaid-graph');

            // Inject stats into sidebar
            var sidebar = document.getElementById('sidebar');
            if (!sidebar) return;
            var div = document.createElement('div');
            div.id = 'header-stats';
            div.innerHTML =
                '<span class="stat">' +
                    '<span class="status-dot idle" id="status-dot"></span>' +
                    '<span class="stat-value" id="status-text">IDLE</span>' +
                '</span>' +
                '<span class="stat">' +
                    '<span class="stat-label">Nodes</span>' +
                    '<span class="stat-value" id="node-count">0</span>' +
                '</span>' +
                '<span class="stat">' +
                    '<span class="stat-label">Topics</span>' +
                    '<span class="stat-value" id="topic-count">0</span>' +
                '</span>' +
                '<span class="stat">' +
                    '<span class="stat-label">Uptime</span>' +
                    '<span class="stat-value" id="uptime">0s</span>' +
                '</span>' +
                '<span class="stat">' +
                    '<span class="stat-label">LLM</span>' +
                    '<span class="stat-value" id="llm-model">\u2014</span>' +
                '</span>';
            sidebar.appendChild(div);

            // Uptime clock
            setInterval(function() {
                var el = document.getElementById('uptime');
                if (!el) return;
                var sec = Math.floor((Date.now() / 1000) - self.startTime);
                if (sec < 60) { el.textContent = sec + 's'; }
                else if (sec < 3600) {
                    el.textContent = Math.floor(sec / 60) + 'm ' + (sec % 60) + 's';
                } else {
                    var h = Math.floor(sec / 3600);
                    var m = Math.floor((sec % 3600) / 60);
                    el.textContent = h + 'h ' + m + 'm';
                }
            }, 1000);
        },

        renderMermaid: function(diagram) {
            var el = this.mermaidEl;
            if (!el || !diagram) return;
            try {
                el.removeAttribute('data-processed');
                el.textContent = diagram;
                mermaid.run({ nodes: [el] });
            } catch(e) {
                console.error("Mermaid rendering failed:", e, diagram);
            }
        },

        setBusy: function(busy) {
            var dot = document.getElementById('status-dot');
            var txt = document.getElementById('status-text');
            if (!dot || !txt) return;
            if (busy) {
                dot.className = 'status-dot busy';
                txt.textContent = 'BUSY';
            } else {
                dot.className = 'status-dot idle';
                txt.textContent = 'IDLE';
            }
        },

        on_ws_msg: function(msg) {
            switch(msg.type) {
                case 'topic_msg':
                    var entry = document.createElement('div');
                    entry.className = 'log-entry';
                    var ts = new Date(msg.data.ts * 1000).toLocaleTimeString();
                    var d = (msg.data.data || '').substring(0, 120);
                    entry.innerHTML = '<span class="ts">[' + ts + ']</span>' +
                        ' <span class="topic">' + msg.data.topic + '</span>' +
                        ' <span class="data">' + d + '</span>';
                    this.logEl.appendChild(entry);
                    if (this.logEl.children.length > this.maxLogLines) {
                        this.logEl.removeChild(this.logEl.firstChild);
                    }
                    this.logEl.scrollTop = this.logEl.scrollHeight;
                    break;
                case 'stats':
                    if (msg.data.nodes !== undefined) {
                        document.getElementById('node-count').textContent = msg.data.nodes;
                    }
                    if (msg.data.topics !== undefined) {
                            document.getElementById('topic-count').textContent = msg.data.topics;
                        }
                    if (msg.data.model) {
                            document.getElementById('llm-model').textContent = msg.data.model;
                        }
                    break;
                case 'busy':
                    this.setBusy(msg.data.busy);
                    break;
                case 'mermaid_diagram':
                    this.renderMermaid(msg.data);
                    break;
            }
        }
        """
