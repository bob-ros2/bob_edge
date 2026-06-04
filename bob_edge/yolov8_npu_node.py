#!/usr/bin/env python3
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

"""YOLOv8 Object Detection node using Rockchip RK3588 NPU acceleration."""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# Try importing RKNN Lite library
try:
    from rknnlite.api import RKNNLite
    HAS_RKNN = True
except ImportError:
    HAS_RKNN = False

COCO_CLASSES = [
    'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light',
    'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
    'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
    'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard',
    'tennis racket', 'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
    'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
    'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard', 'cell phone',
    'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear',
    'hair drier', 'toothbrush'
]


# Threaded HTTP Server to handle multi-client MJPEG streaming
class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    node = None


class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Override to suppress spammy HTTP GET logging in terminal
        pass

    def do_GET(self):
        if self.path == '/mjpeg':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
            self.end_headers()
            
            while rclpy.ok():
                try:
                    frame = self.server.node.get_processed_frame()
                    if frame is None:
                        time.sleep(0.03)
                        continue
                        
                    ret, jpeg = cv2.imencode('.jpg', frame)
                    if not ret:
                        time.sleep(0.03)
                        continue
                        
                    self.wfile.write(b'--jpgboundary\r\n')
                    self.send_header('Content-type', 'image/jpeg')
                    self.send_header('Content-length', str(len(jpeg)))
                    self.end_headers()
                    self.wfile.write(jpeg.tobytes())
                    self.wfile.write(b'\r\n')
                    time.sleep(0.05)  # cap stream output to ~20 FPS to save network bandwidth
                except Exception:
                    break


class YOLOv8NPU(Node):
    def __init__(self):
        super().__init__('yolov8_npu')
        
        # ROS 2 Parameters
        self.declare_parameter('model_path', '/home/rosuser/agent/models/yolov8n.rknn')
        self.declare_parameter('camera_index', 0)
        self.declare_parameter('conf_threshold', 0.4)
        self.declare_parameter('nms_threshold', 0.45)
        self.declare_parameter('http_port', 8080)
        
        self.model_path = self.get_parameter('model_path').get_parameter_value().string_value
        self.camera_index = self.get_parameter('camera_index').get_parameter_value().integer_value
        self.conf_threshold = self.get_parameter('conf_threshold').get_parameter_value().double_value
        self.nms_threshold = self.get_parameter('nms_threshold').get_parameter_value().double_value
        self.http_port = self.get_parameter('http_port').get_parameter_value().integer_value

        # Publishers
        self.detections_pub = self.create_publisher(String, '/agent/vision/detections', 10)
        self.npu_stats_pub = self.create_publisher(String, '/agent/vision/npu_stats', 10)

        # Threading and synchronization
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.processed_frame = None
        
        self.is_running = True
        self.fps = 0.0
        self.latency = 0.0
        self.npu_load_str = "Core0: 0%"

        # Initialize NPU / RKNN Runtime
        self.rknn = None
        self.simulation_mode = True

        if HAS_RKNN:
            if os.path.exists(self.model_path):
                self.get_logger().info(f"Loading RKNN model from {self.model_path}...")
                try:
                    self.rknn = RKNNLite()
                    ret = self.rknn.load_rknn(self.model_path)
                    if ret == 0:
                        ret = self.rknn.init_runtime()
                        if ret == 0:
                            self.simulation_mode = False
                            self.get_logger().info("RKNN Runtime initialized successfully on NPU!")
                        else:
                            self.get_logger().error("Failed to init RKNN Runtime. Falling back to simulation.")
                    else:
                        self.get_logger().error("Failed to load RKNN model. Falling back to simulation.")
                except Exception as e:
                    self.get_logger().error(f"Error initializing NPU runtime: {e}. Falling back to simulation.")
            else:
                self.get_logger().warn(
                    f"RKNN Model file not found at {self.model_path}. "
                    "Running in SIMULATION MODE. Please upload model to enable NPU inference."
                )
        else:
            self.get_logger().warn("rknnlite library not found. Running in SIMULATION MODE.")

        # Initialize camera
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            self.get_logger().error(f"Failed to open USB camera index {self.camera_index}")
            self.get_logger().info("Using simulated background pattern for camera stream.")
            self.cap = None

        # Start HTTP server thread
        self.start_http_server()

        # Start Processing Thread
        self.process_thread = threading.Thread(target=self.processing_loop, daemon=True)
        self.process_thread.start()

        # Timer to publish NPU/Device telemetry
        self.create_timer(2.0, self.publish_telemetry)

    def start_http_server(self):
        try:
            self.http_server = ThreadedHTTPServer(('0.0.0.0', self.http_port), MJPEGHandler)
            self.http_server.node = self
            self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
            self.http_thread.start()
            self.get_logger().info(f"MJPEG HTTP stream available at http://localhost:{self.http_port}/mjpeg")
        except Exception as e:
            self.get_logger().error(f"Failed to start MJPEG HTTP server: {e}")

    def get_processed_frame(self):
        with self.frame_lock:
            if self.processed_frame is not None:
                return self.processed_frame.copy()
            return self.generate_placeholder_frame("Kamera startet...")

    def generate_placeholder_frame(self, text="Camera Feed"):
        # Generate a cool grid pattern if camera fails to open
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        # Background mesh
        for i in range(0, 480, 40):
            cv2.line(img, (0, i), (640, i), (15, 20, 30), 1)
        for j in range(0, 640, 40):
            cv2.line(img, (j, 0), (j, 480), (15, 20, 30), 1)
        # Text
        cv2.putText(img, text, (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (88, 166, 255), 2)
        cv2.putText(img, "YOLOv8 NPU Node", (50, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (139, 148, 158), 1)
        return img

    def publish_telemetry(self):
        # Read NPU load if on board
        if not self.simulation_mode:
            try:
                with open("/sys/kernel/debug/rknpu/load", "r") as f:
                    self.npu_load_str = f.read().strip()
            except Exception:
                self.npu_load_str = "Core0: N/A"
        else:
            # Simulate slight load fluctuations for demo
            load = int(10 + 5 * np.sin(time.time() / 10.0))
            self.npu_load_str = f"Core0: {load}%, Core1: 0%, Core2: 0%"

        stats = {
            "fps": self.fps,
            "latency": self.latency,
            "npu_load": self.npu_load_str
        }
        msg = String()
        msg.data = json.dumps(stats)
        self.npu_stats_pub.publish(msg)

    def xywh2xyxy(self, x):
        # Convert bounding box format [x, y, w, h] to [x1, y1, x2, y2]
        y = np.copy(x)
        y[..., 0] = x[..., 0] - x[..., 2] / 2  # top left x
        y[..., 1] = x[..., 1] - x[..., 3] / 2  # top left y
        y[..., 2] = x[..., 0] + x[..., 2] / 2  # bottom right x
        y[..., 3] = x[..., 1] + x[..., 3] / 2  # bottom right y
        return y

    def post_process_yolov8(self, output, orig_w, orig_h):
        # YOLOv8 standard output shape is (1, 84, 8400)
        # 84 channels: 4 box coords + 80 class scores. 8400 anchors.
        boxes = []
        confidences = []
        class_ids = []

        pred = np.squeeze(output)  # shape (84, 8400)
        pred = np.transpose(pred)   # shape (8400, 84)

        for i in range(pred.shape[0]):
            row = pred[i]
            classes_scores = row[4:]
            class_id = np.argmax(classes_scores)
            confidence = classes_scores[class_id]
            
            if confidence > self.conf_threshold:
                # Box center-x, center-y, width, height (scaled 0-640)
                xc, yc, w, h = row[0], row[1], row[2], row[3]
                
                # Convert to top-left x, y, width, height
                x1 = int((xc - w/2) * orig_w / 640.0)
                y1 = int((yc - h/2) * orig_h / 640.0)
                box_w = int(w * orig_w / 640.0)
                box_h = int(h * orig_h / 640.0)
                
                boxes.append([x1, y1, box_w, box_h])
                confidences.append(float(confidence))
                class_ids.append(int(class_id))

        # Perform NMS using OpenCV to filter overlapping boxes
        indices = cv2.dnn.NMSBoxes(boxes, confidences, self.conf_threshold, self.nms_threshold)
        
        detections = []
        if len(indices) > 0:
            for idx in indices.flatten():
                box = boxes[idx]
                detections.append({
                    "class_name": COCO_CLASSES[class_ids[idx]] if class_ids[idx] < len(COCO_CLASSES) else "unknown",
                    "confidence": confidences[idx],
                    "box": [box[0], box[1], box[2], box[3]]  # x1, y1, w, h
                })
        return detections

    def run_npu_inference(self, frame):
        h, w = frame.shape[:2]
        
        # Preprocessing: resize to 640x640, convert BGR to RGB
        img_resized = cv2.resize(frame, (640, 640))
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        
        # Add batch dimension to make it 4D: (1, 640, 640, 3)
        img_input = np.expand_dims(img_rgb, axis=0)
        
        t0 = time.time()
        try:
            outputs = self.rknn.inference(inputs=[img_input])
            self.latency = (time.time() - t0) * 1000.0  # ms
            
            if outputs is None or len(outputs) == 0:
                self.get_logger().error("RKNN inference returned None or empty output")
                return []
            
            # Log output shapes once for diagnostic purposes
            if not hasattr(self, '_logged_output_shapes'):
                self._logged_output_shapes = True
                shapes = [o.shape for o in outputs]
                self.get_logger().info(f"RKNN model inference outputs shapes: {shapes}")
                
            # Post-process
            detections = self.post_process_yolov8(outputs[0], w, h)
            return detections
        except Exception as e:
            self.get_logger().error(f"RKNN inference failed: {e}")
            return []

    def run_simulated_inference(self, frame):
        # Fake tracking latency
        self.latency = 2.4 + 1.2 * np.sin(time.time())
        
        # Create a mock detection list that animates a box
        detections = []
        t = time.time()
        
        # Person tracking simulation
        px = int(240 + 80 * np.cos(t / 2.0))
        py = int(180 + 50 * np.sin(t / 3.0))
        detections.append({
            "class_name": "person",
            "confidence": 0.88 + 0.05 * np.cos(t),
            "box": [px, py, 140, 220]
        })
        
        # Cat tracking simulation (intermittent)
        if int(t / 5.0) % 2 == 0:
            cx = int(400 + 40 * np.sin(t / 1.5))
            cy = int(300 + 20 * np.cos(t / 2.0))
            detections.append({
                "class_name": "cat",
                "confidence": 0.76,
                "box": [cx, cy, 100, 80]
            })

        return detections

    def processing_loop(self):
        last_time = time.time()
        frame_count = 0
        
        while self.is_running and rclpy.ok():
            t_frame_start = time.time()
            
            # Read frame
            if self.cap is not None:
                ret, frame = self.cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue
            else:
                # Use placeholder stream if no webcam is available
                frame = self.generate_placeholder_frame("Simuliertes Videosignal (Keine Cam)")
                time.sleep(0.03)

            # Inferenz ausführen
            if not self.simulation_mode:
                detections = self.run_npu_inference(frame)
            else:
                detections = self.run_simulated_inference(frame)

            # Draw bounding boxes and labels on the frame
            for det in detections:
                box = det["box"]
                x1, y1, w_box, h_box = box
                x2, y2 = x1 + w_box, y1 + h_box
                
                # Check bounds
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(frame.shape[1], x2)
                y2 = min(frame.shape[0], y2)
                
                label = f"{det['class_name']} ({det['confidence']:.2f})"
                
                # Draw bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (88, 166, 255), 2)
                
                # Draw label background
                (lbl_w, lbl_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(frame, (x1, y1 - 20), (x1 + lbl_w, y1), (88, 166, 255), -1)
                cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (10, 14, 20), 1)

            # Render overlay information (FPS / Mode)
            mode_text = "NPU Accelerated" if not self.simulation_mode else "Simulation Mode"
            cv2.putText(
                frame, f"{mode_text} - FPS: {self.fps:.1f} - Latency: {self.latency:.1f}ms", 
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (57, 185, 80), 2
            )
            if self.simulation_mode:
                cv2.putText(
                    frame, "RKNN model offline. Place yolov8n.rknn in models dir.", 
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (210, 153, 34), 1
                )

            # Update latest processed frame for HTTP server
            with self.frame_lock:
                self.processed_frame = frame

            # Publish detections JSON over ROS 2 Topic
            det_msg = String()
            det_msg.data = json.dumps({"detections": detections})
            self.detections_pub.publish(det_msg)

            # Calculate FPS
            frame_count += 1
            now = time.time()
            if now - last_time >= 1.0:
                self.fps = frame_count / (now - last_time)
                frame_count = 0
                last_time = now

            # Control frame rate / target sleep (keep loop at ~30 FPS max)
            elapsed = time.time() - t_frame_start
            sleep_time = max(0.001, 0.033 - elapsed)
            time.sleep(sleep_time)

    def shutdown(self):
        self.is_running = False
        if self.cap is not None:
            self.cap.release()
        if self.rknn is not None:
            self.rknn.release()
        try:
            self.http_server.shutdown()
        except Exception:
            pass


def main(args=None):
    rclpy.init(args=args)
    node = YOLOv8NPU()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
