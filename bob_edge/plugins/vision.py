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

"""Dashboard plugin for RK3588 NPU YOLOv8 vision analytics."""

import json
from bob_edge.plugins.base import BasePlugin


class VisionPlugin(BasePlugin):
    name = 'vision'
    display_name = 'Vision & NPU'
    topics = [
        '/agent/vision/detections',
        '/agent/vision/npu_stats',
    ]
    grid_class = 'card full'

    def __init__(self):
        super().__init__()

    def on_ros_msg(self, topic: str, data: str, ts: float):
        try:
            parsed = json.loads(data)
            if topic == '/agent/vision/detections':
                self.send_ws('detections', parsed)
            elif topic == '/agent/vision/npu_stats':
                self.send_ws('npu_stats', parsed)
        except Exception:
            pass

    def html(self):
        return """
        <div class="vision-container">
            <div class="vision-video-panel">
                <h2>Live Kamera Feed (YOLOv8 NPU)</h2>
                <div class="video-wrapper">
                    <img id="npu-camera-feed" src="" alt="Kamera-Feed wird geladen oder Offline..." />
                </div>
            </div>
            <div class="vision-stats-panel">
                <h2>NPU & Analytics Status</h2>
                
                <div class="stat-group">
                    <h3>NPU Telemetrie</h3>
                    <div class="stat-grid">
                        <div class="stat-card">
                            <span class="stat-card-label">Inferenz-FPS</span>
                            <span class="stat-card-val" id="npu-fps">0.0</span>
                        </div>
                        <div class="stat-card">
                            <span class="stat-card-label">Latenz</span>
                            <span class="stat-card-val" id="npu-latency">0 ms</span>
                        </div>
                        <div class="stat-card">
                            <span class="stat-card-label">NPU Last</span>
                            <span class="stat-card-val" id="npu-load">Core0: 0%</span>
                        </div>
                    </div>
                </div>

                <div class="stat-group">
                    <h3>Erkannte Objekte</h3>
                    <div class="detection-list-wrapper">
                        <ul class="detection-list" id="detection-list">
                            <li class="no-detections">Keine Objekte erkannt</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
        """

    def css(self):
        return """
        .vision-container {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 24px;
            width: 100%;
            height: calc(100vh - 120px);
            min-height: 500px;
        }
        @media (max-width: 900px) {
            .vision-container {
                grid-template-columns: 1fr;
                height: auto;
            }
        }
        .vision-video-panel, .vision-stats-panel {
            display: flex;
            flex-direction: column;
            background: #11151c;
            border: 1px solid #242b35;
            border-radius: 12px;
            padding: 20px;
        }
        .video-wrapper {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #07090e;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #1b212a;
            min-height: 360px;
        }
        #npu-camera-feed {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }
        .stat-group {
            margin-top: 16px;
        }
        .stat-group h3 {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #8b949e;
            margin-bottom: 12px;
            border-bottom: 1px solid #21262d;
            padding-bottom: 6px;
        }
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }
        .stat-card {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 6px;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            text-align: center;
        }
        .stat-card-label {
            font-size: 10px;
            color: #8b949e;
            text-transform: uppercase;
        }
        .stat-card-val {
            font-size: 16px;
            font-weight: 600;
            color: #58a6ff;
            font-family: 'JetBrains Mono', monospace;
        }
        .detection-list-wrapper {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 8px;
            height: 220px;
            overflow-y: auto;
            padding: 12px;
        }
        .detection-list {
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .detection-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 12px;
            background: #21262d;
            border-radius: 6px;
            border-left: 3px solid #58a6ff;
        }
        .detection-class {
            font-weight: 500;
            color: #f0f6fc;
        }
        .detection-conf {
            font-size: 12px;
            color: #8b949e;
            background: #0d1117;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'JetBrains Mono', monospace;
        }
        .no-detections {
            color: #8b949e;
            text-align: center;
            padding-top: 40px;
            font-style: italic;
        }
        """

    def js_init(self):
        return """
        init: function() {
            var self = this;
            // Dynamically set image stream URL based on dashboard page host
            var streamUrl = "http://" + window.location.hostname + ":8080/mjpeg";
            var img = document.getElementById("npu-camera-feed");
            if (img) {
                img.src = streamUrl;
                img.onerror = function() {
                    console.log("NPU camera stream offline or inaccessible at: " + streamUrl);
                };
            }
        },
        on_ws_msg: function(msg) {
            if (msg.type === "detections") {
                var list = document.getElementById("detection-list");
                if (!list) return;
                
                var detections = msg.data.detections || [];
                if (detections.length === 0) {
                    list.innerHTML = '<li class="no-detections">Keine Objekte erkannt</li>';
                    return;
                }
                
                var html = "";
                detections.forEach(function(d) {
                    var confPercent = Math.round(d.confidence * 100) + "%";
                    html += '<li class="detection-item">' +
                        '<span class="detection-class">📦 ' + d.class_name + '</span>' +
                        '<span class="detection-conf">' + confPercent + '</span>' +
                        '</li>';
                });
                list.innerHTML = html;
            }
            else if (msg.type === "npu_stats") {
                if (msg.data.fps !== undefined) {
                    document.getElementById("npu-fps").textContent = msg.data.fps.toFixed(1);
                }
                if (msg.data.latency !== undefined) {
                    document.getElementById("npu-latency").textContent = Math.round(msg.data.latency) + " ms";
                }
                if (msg.data.npu_load !== undefined) {
                    document.getElementById("npu-load").textContent = msg.data.npu_load;
                }
            }
        }
        """
