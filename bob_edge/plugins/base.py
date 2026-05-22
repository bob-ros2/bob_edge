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
"""
Abstract plugin base for ws_dashboard.

Each plugin defines:
- name: unique slug
- display_name: human-readable title
- topics: ROS topics to subscribe to
- html(): returns HTML fragment (a <div class="card"> block)
- css(): returns CSS block
- js(): returns JS object with: init(), on_ws_msg(msg), on_ros_msg(msg)
- ws_outbound(msg_type, data): helper to send data to frontend
"""

from abc import ABC, abstractmethod
from typing import Any


class BasePlugin(ABC):
    name: str = ""
    display_name: str = ""
    topics: list[str] = []
    grid_class: str = "card"  # default CSS class, "card full" for full-width

    def __init__(self):
        self._queue = None  # reference to the shared data_queue
        self._publisher_func = None  # callable(topic, msg) for ROS publish

    def setup(self, queue, publisher_func):
        """Call during plugin registration."""
        self._queue = queue
        self._publisher_func = publisher_func

    def publish_ros(self, topic: str, message: str):
        """Publish a string message to a ROS topic."""
        if self._publisher_func:
            self._publisher_func(topic, message)

    def send_ws(self, msg_type: str, data: Any):
        """Queue a message to be sent to all WebSocket clients."""
        if self._queue is not None:
            self._queue.put({
                "plugin": self.name,
                "type": msg_type,
                "data": data,
            })

    @abstractmethod
    def html(self) -> str:
        """Return HTML fragment for this plugin's card(s)."""
        ...

    def css(self) -> str:
        """Return CSS block for this plugin. Override to add styles."""
        return ""

    def js_init(self) -> str:
        """
        Return JS code that runs once on page load.

        Called as: Dashboard.register('{name}', {{ init() {{...}}, on_ws_msg(msg) {{...}} }})
        """
        return """
        init: function() { },
        on_ws_msg: function(msg) { }
        """

    @abstractmethod
    def on_ros_msg(self, topic: str, data: str, ts: float):
        """Call when a subscribed ROS topic receives a message."""
        ...

    def on_ws_msg(self, msg: dict):
        """Call when the frontend sends a message to this plugin."""
        pass
