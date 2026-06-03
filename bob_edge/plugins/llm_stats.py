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
"""Plugin for displaying real-time LLM telemetry and statistics."""

import json

from bob_edge.plugins.base import BasePlugin


class LlmStatsPlugin(BasePlugin):
    """Plugin to track context memory, completion tokens, and generation speed."""

    name = 'llm_stats'
    display_name = 'LLM Telemetry'
    topics = ['/agent/llm_stats']
    grid_class = 'card'

    def on_ros_msg(self, topic: str, data: str, ts: float):
        """Handle incoming ROS 2 messages for LLM stats."""
        if topic == '/agent/llm_stats':
            try:
                stats = json.loads(data)
                self.send_ws('stats_update', stats)
            except Exception:
                pass

    def html(self) -> str:
        """Return the HTML structure for the telemetry card."""
        return '''
        <div class="card full" id="plugin-llm-stats">
            <h2>🧠 LLM Real-Time Telemetry</h2>
            
            <div class="metrics-grid">
                <!-- Context Memory Usage -->
                <div class="metric-card">
                    <h3>Context Memory</h3>
                    <div class="gauge-container">
                        <svg viewBox="0 0 100 100" class="gauge">
                            <circle cx="50" cy="50" r="40" class="gauge-bg"></circle>
                            <circle cx="50" cy="50" r="40" class="gauge-fill" id="ctx-gauge-fill"></circle>
                        </svg>
                        <div class="gauge-value" id="ctx-gauge-percent">0%</div>
                    </div>
                    <div class="metric-info">
                        <span id="ctx-tokens-details">0 / 0 tokens</span>
                        <span class="sub" id="ctx-tokens-remaining">Remaining: —</span>
                    </div>
                </div>

                <!-- Completion Details -->
                <div class="metric-card">
                    <h3>Response Output</h3>
                    <div class="output-counter" id="output-tokens-val">0</div>
                    <div class="status-badge" id="llm-status-badge">Idle</div>
                    <div class="metric-info">
                        <span>Output Tokens</span>
                        <span class="sub" id="max-tokens-details">Max limit: —</span>
                    </div>
                </div>

                <!-- Speed & Performance -->
                <div class="metric-card">
                    <h3>Generation Speed</h3>
                    <div class="speed-value"><span id="speed-val">0.0</span> <span class="unit">t/s</span></div>
                    <div class="performance-indicator" id="performance-quality">Ready</div>
                    <div class="metric-info">
                        <span>Tokens per second</span>
                        <span class="sub" id="last-update-ts">Last update: —</span>
                    </div>
                </div>
            </div>

            <!-- Real-time Chart and raw text -->
            <div class="chart-section">
                <h3>Speed History (t/s)</h3>
                <div style="height: 160px; position: relative; width: 100%;">
                    <canvas id="speed-history-chart"></canvas>
                </div>
            </div>

            <div class="console-section">
                <h3>Formatted Status</h3>
                <div id="formatted-console-status">Waiting for telemetry...</div>
            </div>
        </div>
        '''

    def css(self) -> str:
        """Return CSS styles for the telemetry elements."""
        return '''
        #plugin-llm-stats {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            width: 100%;
        }
        .metric-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            position: relative;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .metric-card::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; height: 3px;
            background: linear-gradient(90deg, var(--accent), #8b5cf6);
            opacity: 0.8;
        }
        .metric-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }
        .metric-card h3 {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin-bottom: 16px;
            font-weight: 600;
        }
        .gauge-container {
            position: relative;
            width: 100px;
            height: 100px;
            margin-bottom: 12px;
        }
        .gauge {
            transform: rotate(-90deg);
            width: 100px;
            height: 100px;
        }
        .gauge-bg {
            fill: none;
            stroke: #21262d;
            stroke-width: 8;
        }
        .gauge-fill {
            fill: none;
            stroke: var(--accent);
            stroke-width: 8;
            stroke-linecap: round;
            stroke-dasharray: 251.2;
            stroke-dashoffset: 251.2;
            transition: stroke-dashoffset 0.5s ease, stroke 0.5s ease;
        }
        .gauge-value {
            position: absolute;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            font-size: 18px;
            font-weight: 600;
            color: var(--text-main);
        }
        .output-counter {
            font-size: 36px;
            font-weight: 600;
            color: #f0f6fc;
            margin: 10px 0;
        }
        .status-badge {
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            margin-bottom: 12px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .status-badge.generating {
            background: rgba(210, 153, 34, 0.15);
            color: #d29922;
            border: 1px solid rgba(210, 153, 34, 0.3);
            animation: pulse-border-stats 1.5s infinite;
        }
        .status-badge.completed {
            background: rgba(63, 185, 80, 0.15);
            color: #3fb950;
            border: 1px solid rgba(63, 185, 80, 0.3);
        }
        .status-badge.error {
            background: rgba(248, 81, 73, 0.15);
            color: #f85149;
            border: 1px solid rgba(248, 81, 73, 0.3);
        }
        @keyframes pulse-border-stats {
            0%, 100% { border-color: rgba(210, 153, 34, 0.3); }
            50% { border-color: rgba(210, 153, 34, 0.8); }
        }
        .speed-value {
            font-size: 32px;
            font-weight: 600;
            color: #f0f6fc;
            margin: 12px 0 8px 0;
        }
        .speed-value .unit {
            font-size: 14px;
            color: var(--text-muted);
        }
        .performance-indicator {
            font-size: 12px;
            font-weight: 500;
            margin-bottom: 12px;
            color: #8b949e;
        }
        .metric-info {
            display: flex;
            flex-direction: column;
            gap: 2px;
            font-size: 13px;
            color: var(--text-main);
        }
        .metric-info .sub {
            font-size: 11px;
            color: var(--text-muted);
        }
        .chart-section, .console-section {
            background: rgba(255, 255, 255, 0.01);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }
        .chart-section h3, .console-section h3 {
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin-bottom: 14px;
            font-weight: 600;
        }
        #formatted-console-status {
            background: #0d1117;
            border: 1px solid #21262d;
            border-radius: 6px;
            padding: 12px;
            font-family: "JetBrains Mono", monospace;
            font-size: 13px;
            color: #58a6ff;
            word-break: break-all;
        }
        '''

    def js_init(self) -> str:
        """Return JavaScript initialization code."""
        return '''
        init: function() {
            var self = this;
            this.maxChartPoints = 30;
            this.speedsHistory = [];
            this.labelsHistory = [];

            this.ctxGaugeFill = document.getElementById("ctx-gauge-fill");
            this.ctxGaugePercent = document.getElementById("ctx-gauge-percent");
            this.ctxTokensDetails = document.getElementById("ctx-tokens-details");
            this.ctxTokensRemaining = document.getElementById("ctx-tokens-remaining");
            this.outputTokensVal = document.getElementById("output-tokens-val");
            this.maxTokensDetails = document.getElementById("max-tokens-details");
            this.speedVal = document.getElementById("speed-val");
            this.statusBadge = document.getElementById("llm-status-badge");
            this.performanceQuality = document.getElementById("performance-quality");
            this.lastUpdateTs = document.getElementById("last-update-ts");
            this.formattedConsole = document.getElementById("formatted-console-status");

            var canvas = document.getElementById("speed-history-chart");
            if (canvas) {
                this.chart = new Chart(canvas, {
                    type: "line",
                    data: {
                        labels: this.labelsHistory,
                        datasets: [{
                            label: "Speed (t/s)",
                            data: this.speedsHistory,
                            borderColor: "#58a6ff",
                            backgroundColor: "rgba(88, 166, 255, 0.05)",
                            borderWidth: 2,
                            fill: true,
                            tension: 0.3,
                            pointRadius: 1,
                            pointHoverRadius: 5
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            tooltip: { enabled: true }
                        },
                        scales: {
                            x: { display: false },
                            y: {
                                grid: { color: "rgba(255, 255, 255, 0.05)" },
                                ticks: { color: "#8b949e", font: { family: "Inter", size: 10 } },
                                min: 0
                            }
                        }
                    }
                });
            }

            var retryCount = 0;
            function tryInject() {
                if (self.injectSidebarStats()) {
                    return;
                }
                if (retryCount < 40) {
                    retryCount++;
                    setTimeout(tryInject, 150);
                }
            }
            tryInject();
        },

        injectSidebarStats: function() {
            var llmEl = document.getElementById("llm-model");
            if (!llmEl) return false;
            var statSpan = llmEl.closest(".stat");
            if (!statSpan) return false;

            if (document.getElementById("sidebar-llm-stats")) return true;

            var container = document.createElement("div");
            container.id = "sidebar-llm-stats";
            container.style.marginTop = "12px";
            container.style.paddingTop = "12px";
            container.style.borderTop = "1px solid #242b35";
            container.style.display = "flex";
            container.style.flexDirection = "column";
            container.style.gap = "6px";
            container.style.fontSize = "11px";
            container.style.color = "var(--text-muted)";

            container.innerHTML = `
                <div style="display: flex; justify-content: space-between; font-weight: 500;">
                    <span style="color: var(--accent);">LLM TELEMETRY</span>
                    <span id="sidebar-status-lbl" style="text-transform: uppercase;">IDLE</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 4px;">
                    <span>Context:</span>
                    <span id="sidebar-ctx-val" style="color: var(--text-main);">— / —</span>
                </div>
                <div style="background: #21262d; border-radius: 4px; height: 5px; overflow: hidden; width: 100%; margin-top: 2px;">
                    <div id="sidebar-ctx-bar" style="background: #3fb950; width: 0%; height: 100%; transition: width 0.3s ease;"></div>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span>Output:</span>
                    <span id="sidebar-out-val" style="color: var(--text-main);">—</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span>Speed:</span>
                    <span id="sidebar-speed-val" style="color: var(--text-main); font-weight: 500;">—</span>
                </div>
            `;
            statSpan.parentNode.insertBefore(container, statSpan.nextSibling);
            return true;
        },

        updateColor: function(percent) {
            if (percent < 50) return "#3fb950";
            if (percent < 80) return "#d29922";
            return "#f85149";
        },

        on_ws_msg: function(msg) {
            if (msg.type !== "stats_update") return;
            var data = msg.data;
            if (!data) return;

            this.injectSidebarStats();

            var pTokens = data.prompt_tokens || 0;
            var ctxLimit = data.context_limit || 0;
            var ctxPercent = data.context_percent !== undefined ? data.context_percent : 0;
            var cTokens = data.completion_tokens || 0;
            var maxTokens = data.max_tokens;
            var speed = data.tokens_per_second || 0;
            var status = data.status || "idle";
            var formatted = data.formatted || "—";

            var color = this.updateColor(ctxPercent);

            var sStatus = document.getElementById("sidebar-status-lbl");
            var sCtxVal = document.getElementById("sidebar-ctx-val");
            var sCtxBar = document.getElementById("sidebar-ctx-bar");
            var sOutVal = document.getElementById("sidebar-out-val");
            var sSpeedVal = document.getElementById("sidebar-speed-val");

            if (sStatus) {
                sStatus.textContent = status;
                sStatus.style.color = status === "generating" ? "#d29922" : (status === "completed" ? "#3fb950" : "#f85149");
            }
            if (sCtxVal) {
                sCtxVal.textContent = pTokens + " / " + ctxLimit + " (" + ctxPercent + "%)";
            }
            if (sCtxBar) {
                sCtxBar.style.width = ctxPercent + "%";
                sCtxBar.style.backgroundColor = color;
            }
            if (sOutVal) {
                sOutVal.textContent = cTokens + " / " + (maxTokens || "∞");
            }
            if (sSpeedVal) {
                sSpeedVal.textContent = status === "completed" ? "Done" : (speed > 0 ? speed.toFixed(1) + " t/s" : "—");
            }

            if (this.ctxGaugeFill) {
                var offset = 251.2 - (251.2 * ctxPercent / 100);
                this.ctxGaugeFill.style.strokeDashoffset = offset;
                this.ctxGaugeFill.style.stroke = color;
            }
            if (this.ctxGaugePercent) {
                this.ctxGaugePercent.textContent = ctxPercent + "%";
                this.ctxGaugePercent.style.color = color;
            }
            if (this.ctxTokensDetails) {
                this.ctxTokensDetails.textContent = pTokens + " / " + ctxLimit + " tokens";
            }
            if (this.ctxTokensRemaining) {
                var remaining = ctxLimit - pTokens;
                this.ctxTokensRemaining.textContent = "Remaining: " + (remaining >= 0 ? remaining : 0) + " tokens";
            }
            if (this.outputTokensVal) {
                this.outputTokensVal.textContent = cTokens;
            }
            if (this.maxTokensDetails) {
                this.maxTokensDetails.textContent = "Max limit: " + (maxTokens || "None");
            }
            if (this.speedVal) {
                this.speedVal.textContent = speed.toFixed(1);
            }
            if (this.statusBadge) {
                this.statusBadge.textContent = status;
                this.statusBadge.className = "status-badge " + status;
            }
            if (this.performanceQuality) {
                if (status === "generating") {
                    this.performanceQuality.textContent = "Active generation...";
                    this.performanceQuality.style.color = "#d29922";
                } else if (status === "completed") {
                    this.performanceQuality.textContent = "Finished generation";
                    this.performanceQuality.style.color = "#3fb950";
                } else {
                    this.performanceQuality.textContent = "Ready";
                    this.performanceQuality.style.color = "#8b949e";
                }
            }
            if (this.lastUpdateTs) {
                this.lastUpdateTs.textContent = "Last update: " + new Date().toLocaleTimeString();
            }
            if (this.formattedConsole) {
                this.formattedConsole.textContent = formatted;
            }

            if (this.chart) {
                var label = new Date().toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit"
                });
                this.speedsHistory.push(speed);
                this.labelsHistory.push(label);

                if (this.speedsHistory.length > this.maxChartPoints) {
                    this.speedsHistory.shift();
                    this.labelsHistory.shift();
                }
                this.chart.update();
            }
        }
        '''
