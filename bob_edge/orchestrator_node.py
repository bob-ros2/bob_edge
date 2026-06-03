# Copyright 2026 Bob Ros
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

from datetime import datetime
import json
import re
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class OrchestratorNode(Node):
    """
    Central node that orchestrates user queries and specialist responses.

    Handles busy-locking, queuing, and support-routing.
    """

    def __init__(self):
        super().__init__('orchestrator')

        # Parameters
        self.declare_parameter('enable_queuing', False)
        self.declare_parameter('reject_if_busy', True)
        self.declare_parameter('busy_timeout', 300.0)

        # State
        self.is_busy = False
        self.last_user_query = ''
        self.is_detailed = False
        self.query_queue = []
        self.was_streamed = False
        self.busy_since = None  # Timestamp for watchdog
        self.user_contexts = {}  # { "username": "context_str" }
        self.user_regex = re.compile(r'^([^ ]+):.*$')

        # QoS for high-speed streaming (Volatile, Reliable, Depth 100)
        qos_stream = rclpy.qos.QoSProfile(
            depth=100,
            durability=rclpy.qos.DurabilityPolicy.VOLATILE,
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE)

        # Publishers
        self.pub_timed_query = self.create_publisher(
            String, 'user_query_timed', 10)
        self.pub_user_response = self.create_publisher(
            String, 'user_response', 10)
        self.pub_dispatched_query = self.create_publisher(
            String, 'llm_query_trigger', 10)
        self.pub_llm_stream = self.create_publisher(
            String, 'llm_stream', qos_stream)

        # Subscriptions
        self.sub_user_query = self.create_subscription(
            String, 'user_query', self.user_query_callback, 10
        )
        self.sub_specialist_response = self.create_subscription(
            String,
            'specialist_response',
            self.specialist_response_callback,
            10
        )
        self.sub_internal_stream = self.create_subscription(
            String,
            'internal/agent_stream',
            self.internal_stream_callback,
            qos_stream
        )

        # Support Assistant Bridge (Neutralized from Bobassi)
        self.pub_support_query = self.create_publisher(
            String, 'support_query', 10)

        self.sub_support_response = self.create_subscription(
            String,
            'support_response',
            self.support_response_callback,
            10
        )

        # Context Support (ESTM)
        self.sub_user_context = self.create_subscription(
            String,
            'memory/active_user_context',
            self.context_callback,
            10
        )

        # Feedback topic for status updates and rejected queries
        self.pub_rejected = self.create_publisher(
            String, 'rejected_queries', 10)

        # Dashboard / UI Monitoring
        self.pub_status = self.create_publisher(
            String, 'internal/status', 10)
        self.pub_visual_trigger = self.create_publisher(
            String, 'internal/visual_trigger', 10)
        self.timer_status = self.create_timer(1.0, self.publish_status)

        self.get_logger().info('Orchestrator ready.')

    @property
    def enable_queuing(self):
        """Return the enable_queuing parameter value."""
        return self.get_parameter('enable_queuing').value

    @property
    def reject_if_busy(self):
        """Return the reject_if_busy parameter value."""
        return self.get_parameter('reject_if_busy').value

    def internal_stream_callback(self, msg):
        """Pass internal tokens to public stream and mark as streamed."""
        self.was_streamed = True
        self.busy_since = self.get_clock().now()
        self.pub_llm_stream.publish(msg)

    def context_callback(self, msg):
        """Update the local user context cache."""
        try:
            data = json.loads(msg.data)
            username = data.get('user_name', '').lower()
            context = data.get('context')
            if username and context:
                self.user_contexts[username] = context
                self.get_logger().debug(f'Updated context for {username}')
        except Exception as e:
            self.get_logger().error(f'Error updating context: {e}')

    def user_query_callback(self, msg):
        """Receive and route user queries."""
        self.was_streamed = False
        query = msg.data

        # Concurrency Check
        if self.is_busy:
            if self.reject_if_busy:
                self.get_logger().info(
                    f'AGENT BUSY -> Routing to SUPPORT: "{query[:40]}..."')
                # Forward to Support Assistant
                support_msg = String()
                support_msg.data = query
                self.pub_support_query.publish(support_msg)
                self.pub_dispatched_query.publish(support_msg)
                return
            elif self.enable_queuing:
                self.get_logger().info(f'Queuing query: {query[:30]}...')
                self.query_queue.append(msg)
                return

        self.get_logger().info(f'AGENT IDLE -> Processing locally: "{query[:40]}..."')
        # Mark as busy and Update UI
        self.is_busy = True
        self.busy_since = self.get_clock().now()
        self.trigger_visual_status(is_busy=True)
        self.process_query(msg)

    def publish_status(self):
        """Publish the current orchestrator status as JSON."""
        status = {
            'Orchestrator': {
                'State': 'BUSY' if self.is_busy else 'IDLE',
                'Queue_Depth': len(self.query_queue),
                'Last_Query': self.last_user_query[:40],
                'Detailed_Mode': self.is_detailed,
                'Time': datetime.now().strftime('%H:%M:%S')
            }
        }
        msg = String()
        msg.data = json.dumps(status)
        self.pub_status.publish(msg)

        # WATCHDOG: Reset Busy state if stuck for too long
        if self.is_busy and self.busy_since:
            busy_timeout = self.get_parameter('busy_timeout').value
            elapsed = (self.get_clock().now() - self.busy_since).nanoseconds / 1e9
            if elapsed > busy_timeout:
                self.get_logger().error(
                    f'WATCHDOG: Busy state stuck for {elapsed:.1f}s. Resetting to IDLE.')
                self.is_busy = False
                self.busy_since = None
                self.trigger_visual_status(is_busy=False)

    def trigger_visual_status(self, is_busy=False):
        """Publish a trigger for the dashboard visualization worker."""
        msg = String()
        msg.data = 'busy' if is_busy else 'idle'
        self.pub_visual_trigger.publish(msg)

    def process_query(self, msg):
        """Handle the actual routing and timing injection."""
        query = msg.data
        self.last_user_query = query
        self.get_logger().debug(f'Processing query: {query}')

        # Simple Intent/Verbosity Detection
        details_keywords = ['detail', 'verbose', 'explain', 'thorough']
        self.is_detailed = any(k in query.lower() for k in details_keywords)

        self.get_logger().info(
            f'Dispatching query (Detailed={self.is_detailed})')

        # Get current time
        now = datetime.now()
        time_str = now.strftime('%Y-%m-%d %H:%M:%S')
        day_of_week = now.strftime('%A')

        if self.is_detailed:
            verbosity = ('DETAILED (Be thorough, explain facts, '
                         'tell stories if requested)')
        else:
            verbosity = 'CONCISE (Be brief, max 2-3 sentences for fast speech)'

        # User Context Injection
        user_ctx_str = ''
        match = self.user_regex.match(query)
        if match:
            username = match.group(1).lower()  # Force lowercase for matching
            # 1.2s wait to ensure CouchDB response and ROS broadcast arrive.
            time.sleep(1.2)

            history = self.user_contexts.get(username, 'Keine rezenten Informationen verfügbar.')
            user_ctx_str = f' [User "{username}" History:\n{history}]'
            self.get_logger().info(f'Injected context for {username} ({len(history)} bytes)')
            if username == 'support':
                user_ctx_str += (
                    ' [REMARK: This user is the Support Assistant, your core supporter. '
                    'Treat with priority and familiarity.]'
                )

        sys_ctx = (f'[System Context: Current Real Time is '
                   f'{day_of_week}, {time_str}. '
                   f'Verbosity Preference: {verbosity}.{user_ctx_str}] ')
        enriched_query = sys_ctx + query

        routing_data = {'role': 'user', 'content': enriched_query}
        timed_msg = String()
        timed_msg.data = json.dumps(routing_data)
        self.pub_timed_query.publish(timed_msg)

        # Dispatch the raw query as a unified trigger for UI/Visuals
        dispatch_msg = String()
        dispatch_msg.data = query
        self.pub_dispatched_query.publish(dispatch_msg)

    def specialist_response_callback(self, msg):
        """Receive a response from a specialist agent."""
        if not msg.data and not self.was_streamed:
            self.get_logger().warn(
                'Received empty specialist response and no tokens were streamed.')
            self.is_busy = False
            self.trigger_visual_status(is_busy=False)
            return

        content = ''
        if msg.data:
            try:
                try:
                    data = json.loads(msg.data)
                    content = data.get('content', msg.data)
                except json.JSONDecodeError:
                    # Fallback for plain string responses
                    content = msg.data
            except Exception as e:
                self.get_logger().error(f'Error parsing specialist resp: {e}')
                content = msg.data

        # Even if content is empty now, if we streamed, we are done.
        self.get_logger().debug(
            f'Finalizing turn. Streamed: {self.was_streamed}, Content Length: {len(content)}')

        bundled_data = {
            'user_query': self.last_user_query,
            'is_detailed': self.is_detailed,
            'specialist_response': content
        }
        response_msg = String()
        response_msg.data = json.dumps(bundled_data)
        self.pub_user_response.publish(response_msg)

        if content and not self.was_streamed:
            stream_msg = String()
            stream_msg.data = content
            self.pub_llm_stream.publish(stream_msg)

        # RELEASE LOCK
        self.is_busy = False
        self.trigger_visual_status(is_busy=False)

        # Handle Queue
        if self.enable_queuing and self.query_queue:
            self.user_query_callback(self.query_queue.pop(0))

    def support_response_callback(self, msg):
        """Receive a response from the Support Assistant."""
        if not msg.data:
            self.get_logger().warn('Received empty Support response.')
            return

        content = ''
        try:
            try:
                data = json.loads(msg.data)
                content = data.get('content', msg.data)
            except json.JSONDecodeError:
                # Direct string fallback
                content = msg.data

            bundled_data = {
                'user_query': 'Support Request',
                'is_detailed': False,
                'specialist_response': f'[Support]: {content}'
            }
            response_msg = String()
            response_msg.data = json.dumps(bundled_data)
            self.pub_user_response.publish(response_msg)

            if not self.was_streamed:
                stream_msg = String()
                stream_msg.data = content
                self.pub_llm_stream.publish(stream_msg)
        except Exception as e:
            self.get_logger().error(f'Error processing Support response: {e}')


def main(args=None):
    """Start the orchestrator node."""
    rclpy.init(args=args)
    node = OrchestratorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
