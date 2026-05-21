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
"""
Three.js 3D Visualization Plugin.

Mehrere Szenen im Dashboard:
- 3D Punktwolke (pulsierend, rotierend)
- Wireframe-Objekte (dynamisch)
- Token-Stream Visualisierung
"""

import math
import random
import threading
import time
from bob_edge.plugins.base import BasePlugin


class ThreeDPlugin(BasePlugin):
    name = "three_d"
    display_name = "3D Visualisierung"
    topics = [
        "/agent/llm_stream",
        "/agent/llm_reasoning",
        "/agent/llm_tool_calls",
    ]
    grid_class = "card full"

    def __init__(self):
        super().__init__()
        self._running = True
        self._token_buf = ""
        self._t0 = time.time()
        threading.Thread(target=self._cloud_loop, daemon=True).start()
        threading.Thread(target=self._wire_loop, daemon=True).start()

    def _cloud_loop(self):
        """Generate point cloud data at 20fps."""
        t0 = self._t0
        while self._running:
            t = time.time() - t0
            num = 500
            spread = 1.5
            pulse_amp = 0.4
            pulse_speed = 0.8
            rot_speed = 0.4

            # Kugelverteilung
            pts = []
            random.seed(42)
            for _ in range(num):
                theta = random.uniform(0, 2 * math.pi)
                phi = math.acos(2 * random.uniform(0, 1) - 1)
                r = spread * (0.3 + 0.7 * random.uniform(0, 1))
                x = r * math.sin(phi) * math.cos(theta)
                y = r * math.sin(phi) * math.sin(theta)
                z = r * math.cos(phi)

                pulse = 1.0 + pulse_amp * math.sin(2 * math.pi * pulse_speed * t)
                angle = rot_speed * t
                cos_a, sin_a = math.cos(angle), math.sin(angle)
                xr = x * cos_a - z * sin_a
                zr = x * sin_a + z * cos_a

                intensity = 0.3 + 0.7 * (zr + spread) / (2 * spread)
                pts.append({
                    "x": xr * pulse, "y": y * pulse * 0.8, "z": zr * pulse,
                    "r": 0.1 + 0.9 * intensity,
                    "g": 0.3 + 0.7 * intensity,
                    "b": 1.0 * intensity,
                })

            self.send_ws("pointcloud", {
                "points": pts,
                "ts": t,
            })
            time.sleep(1 / 20)

    def _wire_loop(self):
        """Generate wireframe object data at 2fps."""
        t0 = self._t0
        while self._running:
            t = time.time() - t0
            # Torus-Knoten-artige Wire-Struktur
            verts = []
            edges = []
            n_verts = 180
            for i in range(n_verts):
                u = 2 * math.pi * i / n_verts
                # 3D Lissajous/Torus-Knoten
                R1, R2 = 1.2, 0.8
                p, q = 3, 2
                r = R1 + R2 * math.cos(q * u)
                x = r * math.cos(p * u + t * 0.5)
                y = R2 * math.sin(q * u)
                z = r * math.sin(p * u + t * 0.5)
                verts.append({"x": x, "y": y, "z": z})
                edges.append([i, (i + 1) % n_verts])

            self.send_ws("wireframe", {
                "vertices": verts,
                "edges": edges,
                "ts": t,
            })
            time.sleep(1 / 2)

    def on_ros_msg(self, topic: str, data: str, ts: float):
        if topic == "/agent/llm_stream":
            self.send_ws("token_stream", {"token": data})
        elif topic == "/agent/llm_reasoning":
            self.send_ws("reasoning", {"data": data[:500]})
        elif topic == "/agent/llm_tool_calls":
            self.send_ws("tool_call", {"data": data[:500]})

    def on_ws_msg(self, msg: dict):
        if msg.get("type") == "set_color":
            # Zukünftig: Farbe per Frontend-UI ändern
            pass

    def html(self):
        return """
        <div class="card full" id="plugin-3d">
            <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                <h2 style="margin:0;">🌌 3D Visualisierung</h2>
                <div style="display:flex;gap:16px;font-size:12px;">
                    <label style="color:#8b949e;"><input type="checkbox" id="chk-cloud" checked> Cloud</label>
                    <label style="color:#8b949e;"><input type="checkbox" id="chk-wire" checked> Wire</label>
                    <label style="color:#8b949e;"><input type="checkbox" id="chk-tokens" checked> Tokens</label>
                </div>
            </div>
            <div id="three-container" style="width:100%;height:600px;background:#0d1117;"></div>
        </div>
        """

    def css(self):
        return """
        #plugin-3d canvas { display: block; width: 100% !important; height: 100% !important; }
        #plugin-3d label { cursor: pointer; user-select: none; }
        #plugin-3d label input { margin-right: 4px; }
        """

    def js_init(self):
        return """
        init: function() {
            var self = this;
            self.container = document.getElementById('three-container');
            if (!self.container) return;

            // Three.js von CDN laden
            var script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
            script.onload = function() { self._initScene(); };
            document.head.appendChild(script);
        },

        _initScene: function() {
            var self = this;

            // Renderer
            self.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
            self.renderer.setSize(self.container.clientWidth, self.container.clientHeight);
            self.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            self.renderer.setClearColor(0x0d1117);
            self.container.appendChild(self.renderer.domElement);

            // Scene
            self.scene = new THREE.Scene();

            // Camera
            self.camera = new THREE.PerspectiveCamera(50, 
                self.container.clientWidth / self.container.clientHeight, 0.1, 50);
            self.camera.position.set(3, 2, 5);
            self.camera.lookAt(0, 0, 0);

            // Lights
            var ambient = new THREE.AmbientLight(0x404060);
            self.scene.add(ambient);
            var dir = new THREE.DirectionalLight(0xffffff, 0.8);
            dir.position.set(5, 10, 7);
            self.scene.add(dir);
            var dir2 = new THREE.DirectionalLight(0x4488ff, 0.3);
            dir2.position.set(-5, -2, -5);
            self.scene.add(dir2);

            // Point Cloud (Scene 1)
            self.cloudGeo = new THREE.BufferGeometry();
            self.cloudMat = new THREE.PointsMaterial({
                size: 0.08,
                vertexColors: true,
                transparent: true,
                opacity: 0.9,
                blending: THREE.AdditiveBlending,
                depthWrite: false,
                sizeAttenuation: true,
            });
            self.cloudPos = new Float32Array(500 * 3);
            self.cloudCol = new Float32Array(500 * 3);
            self.cloudGeo.setAttribute('position', new THREE.BufferAttribute(self.cloudPos, 3));
            self.cloudGeo.setAttribute('color', new THREE.BufferAttribute(self.cloudCol, 3));
            self.cloudPoints = new THREE.Points(self.cloudGeo, self.cloudMat);
            self.scene.add(self.cloudPoints);
            self.cloudCount = 0;

            // Wireframe (Scene 2)
            self.wireGeo = new THREE.BufferGeometry();
            self.wireMat = new THREE.LineBasicMaterial({
                color: 0x58a6ff,
                transparent: true,
                opacity: 0.6,
            });
            self.wireLine = new THREE.LineSegments(self.wireGeo, self.wireMat);
            self.scene.add(self.wireLine);

            // Token Particles (Scene 3)
            self.tokenCount = 800;
            self.tokenPos = new Float32Array(self.tokenCount * 3);
            self.tokenCol = new Float32Array(self.tokenCount * 3);
            self.tokenVel = [];
            self.tokenLife = [];
            self.tokenT = [];
            for (var i = 0; i < self.tokenCount; i++) {
                self.tokenVel.push(new THREE.Vector3(
                    (Math.random() - 0.5) * 0.02,
                    Math.random() * 0.03 + 0.01,
                    (Math.random() - 0.5) * 0.02
                ));
                var a = Math.random() * 2 * Math.PI;
                var rad = 1.5 + Math.random() * 2;
                self.tokenT.push(Math.random());
            }
            self.tokenGeo = new THREE.BufferGeometry();
            self.tokenMat = new THREE.PointsMaterial({
                size: 0.03,
                vertexColors: true,
                transparent: true,
                opacity: 0.7,
                blending: THREE.AdditiveBlending,
                depthWrite: false,
                sizeAttenuation: true,
            });
            self.tokenGeo.setAttribute('position', new THREE.BufferAttribute(self.tokenPos, 3));
            self.tokenGeo.setAttribute('color', new THREE.BufferAttribute(self.tokenCol, 3));
            self.tokenPoints = new THREE.Points(self.tokenGeo, self.tokenMat);
            self.scene.add(self.tokenPoints);

            // Controls (mousemove orbit)
            self._mouse = { x: 0, y: 0 };
            self._targetRot = { x: 0, y: 0 };
            self._isDragging = false;
            self._lastMX = 0;
            self._lastMY = 0;

            self.renderer.domElement.addEventListener('mousedown', function(e) {
                self._isDragging = true;
                self._lastMX = e.clientX;
                self._lastMY = e.clientY;
            });
            window.addEventListener('mouseup', function() { self._isDragging = false; });
            window.addEventListener('mousemove', function(e) {
                if (self._isDragging) {
                    var dx = e.clientX - self._lastMX;
                    var dy = e.clientY - self._lastMY;
                    self._targetRot.x += dx * 0.01;
                    self._targetRot.y += dy * 0.01;
                    self._lastMX = e.clientX;
                    self._lastMY = e.clientY;
                }
            });
            // Touch
            self.renderer.domElement.addEventListener('touchstart', function(e) {
                if (e.touches.length === 1) {
                    self._isDragging = true;
                    self._lastMX = e.touches[0].clientX;
                    self._lastMY = e.touches[0].clientY;
                }
            }, { passive: true });
            self.renderer.domElement.addEventListener('touchmove', function(e) {
                if (self._isDragging && e.touches.length === 1) {
                    var dx = e.touches[0].clientX - self._lastMX;
                    var dy = e.touches[0].clientY - self._lastMY;
                    self._targetRot.x += dx * 0.01;
                    self._targetRot.y += dy * 0.01;
                    self._lastMX = e.touches[0].clientX;
                    self._lastMY = e.touches[0].clientY;
                }
            }, { passive: true });
            self.renderer.domElement.addEventListener('touchend', function() {
                self._isDragging = false;
            }, { passive: true });

            // Resize
            window.addEventListener('resize', function() {
                var w = self.container.clientWidth;
                var h = self.container.clientHeight;
                self.camera.aspect = w / h;
                self.camera.updateProjectionMatrix();
                self.renderer.setSize(w, h);
            });

            // Checkboxes
            document.getElementById('chk-cloud').addEventListener('change', function(e) {
                self.cloudPoints.visible = e.target.checked;
            });
            document.getElementById('chk-wire').addEventListener('change', function(e) {
                self.wireLine.visible = e.target.checked;
            });
            document.getElementById('chk-tokens').addEventListener('change', function(e) {
                self.tokenPoints.visible = e.target.checked;
            });

            // Token activity
            self._tokenActivity = 0;

            // Animation loop
            self._clock = new THREE.Clock();
            self._animate();
        },

        _animate: function() {
            var self = this;
            requestAnimationFrame(function() { self._animate(); });

            var dt = self._clock.getDelta();
            var t = self._clock.getElapsedTime();

            // Camera (Maus + auto-rotation)
            var autoRotate = !self._isDragging;
            if (autoRotate) {
                self._targetRot.x += dt * 0.15;
            }
            var radius = 6;
            self.camera.position.x = radius * Math.sin(self._targetRot.x) * \
                Math.cos(self._targetRot.y * 0.3);
            self.camera.position.y = 2 + radius * Math.sin(self._targetRot.y * 0.3);
            self.camera.position.z = radius * Math.cos(self._targetRot.x) * \
                Math.cos(self._targetRot.y * 0.3);
            self.camera.lookAt(0, 0, 0);

            // Token particles update
            var decay = 0.98;
            self._tokenActivity *= decay;
            for (var i = 0; i < self.tokenCount; i++) {
                var i3 = i * 3;
                self.tokenT[i] += dt * (0.2 + self._tokenActivity * 2);
                if (self.tokenT[i] > 1) self.tokenT[i] -= 1;
                var a = self.tokenT[i] * 2 * Math.PI + i * 0.1;
                var rad = 0.5 + self.tokenT[i] * 2.5;
                self.tokenPos[i3] = Math.cos(a) * rad;
                self.tokenPos[i3 + 1] = self.tokenT[i] * 3 - 1.5;
                self.tokenPos[i3 + 2] = Math.sin(a) * rad;

                var bright = 0.2 + 0.8 * (1 - self.tokenT[i]);
                var g = 0.3 + 0.7 * bright;
                var b = 0.5 + 0.5 * bright;
                self.tokenCol[i3] = 0.0;
                self.tokenCol[i3 + 1] = g;
                self.tokenCol[i3 + 2] = b;
            }
            self.tokenGeo.attributes.position.needsUpdate = true;
            self.tokenGeo.attributes.color.needsUpdate = true;

            self.renderer.render(self.scene, self.camera);
        },

        on_ws_msg: function(msg) {
            var self = this;
            if (!self.renderer) return;

            switch(msg.type) {
                case 'pointcloud':
                    var pts = msg.data.points;
                    if (!pts || !pts.length) return;
                    var count = Math.min(pts.length, 500);
                    for (var i = 0; i < count; i++) {
                        var p = pts[i];
                        var i3 = i * 3;
                        self.cloudPos[i3] = p.x;
                        self.cloudPos[i3+1] = p.y;
                        self.cloudPos[i3+2] = p.z;
                        self.cloudCol[i3] = p.r;
                        self.cloudCol[i3+1] = p.g;
                        self.cloudCol[i3+2] = p.b;
                    }
                    // Pad rest
                    for (var i = count; i < 500; i++) {
                        var i3 = i * 3;
                        self.cloudPos[i3] = 0;
                        self.cloudPos[i3+1] = 0;
                        self.cloudPos[i3+2] = 0;
                        self.cloudCol[i3] = 0;
                        self.cloudCol[i3+1] = 0;
                        self.cloudCol[i3+2] = 0;
                    }
                    self.cloudGeo.attributes.position.needsUpdate = true;
                    self.cloudGeo.attributes.color.needsUpdate = true;
                    self.cloudGeo.setDrawRange(0, count);
                    self.cloudCount = count;
                    break;

                case 'wireframe':
                    var verts = msg.data.vertices;
                    var edges = msg.data.edges;
                    if (!verts || !edges) return;
                    var positions = [];
                    for (var i = 0; i < edges.length; i++) {
                        var v1 = verts[edges[i][0]];
                        var v2 = verts[edges[i][1]];
                        if (!v1 || !v2) continue;
                        positions.push(v1.x, v1.y, v1.z);
                        positions.push(v2.x, v2.y, v2.z);
                    }
                    self.wireGeo.setAttribute('position',
                        new THREE.Float32BufferAttribute(positions, 3));
                    self.wireGeo.setIndex(null);
                    break;

                case 'token_stream':
                    // Aktivität erhöhen bei Token-Eingang
                    self._tokenActivity = Math.min(1, self._tokenActivity + 0.3);
                    break;
            }
        }
        """
