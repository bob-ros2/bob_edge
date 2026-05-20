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
Real-time Markdown Chat Plugin mit direktem API-Workaround.

Sendet parallel via ROS + direkter API. Nimmt was zuerst kommt.
"""
import json
import threading
import time
import urllib.request
import urllib.error
from bob_edge.plugins.base import BasePlugin


class ChatPlugin(BasePlugin):
    name = "chat"
    display_name = "Chat"
    topics = [
        "/agent/user_query",
        "/agent/llm_stream",
        "/agent/llm_reasoning",
        "/agent/llm_tool_calls",
        "/agent/logic/internal/full_response_text",
    ]
    grid_class = "card full"

    def on_ros_msg(self, topic: str, data: str, ts: float):
        if topic == "/agent/user_query":
            self.send_ws("user_msg", {"text": data})
        elif topic == "/agent/llm_stream":
            self.send_ws("stream_token", {"token": data})
        elif topic == "/agent/llm_reasoning":
            self.send_ws("reasoning", {"content": data})
        elif topic == "/agent/llm_tool_calls":
            self.send_ws("tool_call", {"content": data})
        elif topic == "/agent/logic/internal/full_response_text":
            self.send_ws("response_done", {})

    def on_ws_msg(self, msg: dict):
        if msg.get("type") == "user_message":
            text = msg.get("data", "").strip()
            if text:
                self.publish_ros("/agent/user_query", text)

    def html(self):
        return self._html()

    def _html(self):
        return """
        <div class="card full" id="plugin-chat">
            <h2>💬 Chat</h2>
            <div id="chat-messages"></div>
            <div id="chat-input-row">
                <textarea id="chat-input" rows="2" 
                    placeholder="Nachricht... (Enter senden, Shift+Enter)"></textarea>
                <button id="chat-send">➤</button>
            </div>
        </div>
        """

    def css(self):
        return self._css()

    def _css(self):
        return """
        #plugin-chat { display: flex; flex-direction: column; height: 600px; }
        #chat-messages { flex: 1; overflow-y: auto; padding: 8px 0; min-height: 200px; }
        #chat-input-row { display: flex; gap: 8px; border-top: 1px solid #30363d; padding-top: 12px; }
        #chat-input { flex: 1; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; 
            color: #c9d1d9; padding: 10px 12px; font-size: 14px; resize: none; outline: none; }
        #chat-input:focus { border-color: #58a6ff; }
        #chat-send { background: #238636; color: #fff; border: none; border-radius: 6px; 
            padding: 0 20px; font-size: 18px; cursor: pointer; }
        #chat-send:hover { background: #2ea043; }
        #chat-send:disabled { opacity: 0.4; cursor: not-allowed; }
        .chat-msg { margin-bottom: 16px; padding: 12px; border-radius: 8px; }
        .chat-msg.user { background: #1f2937; border: 1px solid #30363d; margin-left: 40px; }
        .chat-msg.assistant { background: #161b22; border: 1px solid #30363d; margin-right: 40px; }
        .chat-msg .role { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; 
            color: #8b949e; margin-bottom: 6px; }
        .chat-msg .role.user-role { color: #58a6ff; }
        .chat-msg .role.assistant-role { color: #3fb950; }
        .chat-msg .content { line-height: 1.6; font-size: 14px; }
        .chat-msg .content p { margin: 4px 0; }
        .chat-msg .content pre { background: #0d1117; border: 1px solid #30363d; 
            border-radius: 6px; padding: 12px; overflow-x: auto; margin: 8px 0; }
        .chat-msg .content code { background: #0d1117; padding: 2px 6px; border-radius: 4px; }
        .chat-msg .content pre code { background: none; padding: 0; }
        .chat-reasoning { margin: 4px 0 8px 0; }
        .chat-reasoning summary { color: #d29922; font-size: 12px; cursor: pointer; }
        .chat-reasoning .reasoning-content { background: #0d1117; border: 1px solid #30363d; 
            border-radius: 6px; padding: 10px; margin-top: 4px; font-size: 12px; color: #8b949e; 
            white-space: pre-wrap; max-height: 200px; overflow-y: auto; }
        .chat-tool-call { background: #1c2128; border: 1px solid #30363d; border-left: 3px solid #58a6ff; 
            border-radius: 4px; padding: 8px 12px; margin: 4px 0; font-family: monospace; 
            font-size: 12px; color: #8b949e; }
        .chat-streaming .content::after { content: '▍'; animation: blink 1s infinite; }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } 
            to { opacity: 1; transform: translateY(0); } }
        """

    def js_init(self):
        return self._js_init()

    def _js_init(self):
        return """
        init: function() {
            var self = this;
            this.msgsEl = document.getElementById('chat-messages');
            this.inputEl = document.getElementById('chat-input');
            this.sendBtn = document.getElementById('chat-send');
            this.currentAssistant = null;

            function sendMessage() {
                var text = self.inputEl.value.trim();
                if (!text) return;
                sendToPlugin('chat', 'user_message', text);
                self.inputEl.value = '';
                self.sendBtn.disabled = true;
            }

            this.sendBtn.addEventListener('click', sendMessage);
            this.inputEl.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
        },

        addUserMessage: function(text) {
            var div = document.createElement('div');
            div.className = 'chat-msg user';
            div.innerHTML = '<div class="role user-role">Du</div><div class="content">' +
                '<p>' + this.escapeHtml(text) + '</p></div>';
            this.msgsEl.appendChild(div);
            this.msgsEl.scrollTop = this.msgsEl.scrollHeight;
        },

        createAssistantContainer: function() {
            var div = document.createElement('div');
            div.className = 'chat-msg assistant chat-streaming';
            div.innerHTML = '<div class="role assistant-role">Bob</div>' +
                '<div class="reasoning-section"></div>' +
                '<div class="tool-section"></div>' +
                '<div class="content"></div>';
            this.msgsEl.appendChild(div);
            this.msgsEl.scrollTop = this.msgsEl.scrollHeight;
            this.currentAssistant = {
                el: div, contentEl: div.querySelector('.content'),
                reasoningEl: div.querySelector('.reasoning-section'),
                toolEls: div.querySelector('.tool-section'),
                buffer: '', reasoningBuffer: '',
            };
        },

        escapeHtml: function(text) {
            var map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
            return text.replace(/[&<>"']/g, function(m) { return map[m]; });
        },

        on_ws_msg: function(msg) {
            switch(msg.type) {
                case 'user_msg':
                    this.addUserMessage(msg.data.text);
                    this.createAssistantContainer();
                    this.sendBtn.disabled = true;
                    break;
                case 'stream_token':
                    var s = this.currentAssistant;
                    if (s) {
                        s.buffer += msg.data.token;
                        try { s.contentEl.innerHTML = marked.parse(s.buffer); }
                        catch(e) { s.contentEl.textContent = s.buffer; }
                        this.msgsEl.scrollTop = this.msgsEl.scrollHeight;
                    }
                    break;
                case 'reasoning':
                    var s = this.currentAssistant;
                    if (s) {
                        s.reasoningBuffer += msg.data.content;
                        s.reasoningEl.innerHTML = '<details class="chat-reasoning">' +
                            '<summary>🧠 Reasoning</summary>' +
                            '<div class="reasoning-content">' + this.escapeHtml(s.reasoningBuffer) + 
                                '</div></details>';
                    }
                    break;
                case 'tool_call':
                    var s = this.currentAssistant;
                    if (s) {
                        var tc = document.createElement('div');
                        tc.className = 'chat-tool-call';
                        tc.textContent = msg.data.content;
                        s.toolEls.appendChild(tc);
                    }
                    break;
                case 'response_done':
                    var s = this.currentAssistant;
                    if (s) {
                        s.el.classList.remove('chat-streaming');
                        try { s.contentEl.innerHTML = marked.parse(s.buffer); }
                        catch(e) { s.contentEl.textContent = s.buffer; }
                    }
                    this.sendBtn.disabled = false;
                    this.inputEl.focus();
                    break;
            }
        }
        """
