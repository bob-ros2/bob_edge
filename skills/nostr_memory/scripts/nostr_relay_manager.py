#!/usr/bin/env python3
"""
Nostr Relay Manager – Lifecycle management for 3 local Nostr relays.

Controls Docker Compose instances: start, stop, restart, status, logs, clean.

Usage:
    python3 nostr_relay_manager.py --action start
    python3 nostr_relay_manager.py --action status --relay relay2
    python3 nostr_relay_manager.py --action logs --lines 100
"""

import argparse
import json
import os
import subprocess
import sys
import time

# Path to the Docker Compose file (robust path searching)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPOSE_FILE = ''

POSSIBLE_PATHS = [
    # 1. Relative to script (in workspace)
    os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', '..', '..', 'docker', 'compose-nostr.yaml')),
    os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', '..', 'docker', 'compose-nostr.yaml')),
    # 2. Absolute path inside Docker container
    '/ros2_ws/src/bob_edge/docker/compose-nostr.yaml',
    # 3. Absolute path on development host
    '/blue/dev/nostr/ros2_ws/src/bob_edge/docker/compose-nostr.yaml'
]

for p in POSSIBLE_PATHS:
    if os.path.exists(p):
        COMPOSE_FILE = p
        break

if not COMPOSE_FILE:
    # Fallback/Default
    COMPOSE_FILE = POSSIBLE_PATHS[0]

RELAY_NAMES = ['relay1', 'relay2', 'relay3']
RELAY_PORTS = {'relay1': 8781, 'relay2': 8782, 'relay3': 8783}


def _run_compose(args_list, timeout=60):
    """Executes docker compose with the given arguments."""
    cmd = ['docker', 'compose', '-f', COMPOSE_FILE] + args_list
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result
    except subprocess.TimeoutExpired:
        print(f'[ERROR] Docker compose command timed out ({timeout}s): {" ".join(cmd)}',
              file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print('[ERROR] Docker or docker compose not found. Is Docker installed?',
              file=sys.stderr)
        sys.exit(1)


def action_start(relay_filter, confirmed=False):
    """Starts the specified relay containers."""
    if not confirmed and os.environ.get('NOSTR_CONFIRM_LOCAL_RELAY') != '1':
        print('[ABORT] Local relays are not allowed to be started automatically/without confirmation!', file=sys.stderr)
        print('        To start them anyway, set the environment variable NOSTR_CONFIRM_LOCAL_RELAY=1', file=sys.stderr)
        print('        or pass the --confirm argument during manual execution.', file=sys.stderr)
        sys.exit(1)

    print('🚀 Starting Nostr relays...')
    if not os.path.exists(COMPOSE_FILE):
        print(f'[ERROR] Compose file not found: {COMPOSE_FILE}', file=sys.stderr)
        sys.exit(1)

    # Check/ensure network exists
    subprocess.run(
        ['docker', 'network', 'create', 'agent-net'],
        capture_output=True, text=True
    )  # Ignore error (already exists)

    if relay_filter == 'all':
        result = _run_compose(['up', '-d'])
        print(result.stdout)
        if result.returncode != 0:
            print(f'[ERROR] {result.stderr}', file=sys.stderr)
            sys.exit(1)

        # Wait briefly until containers are actually running
        time.sleep(3)

        # Show status
        action_status('all')
    else:
        # Start only specific relays
        result = _run_compose(['up', '-d', relay_filter])
        print(result.stdout)
        if result.returncode != 0:
            print(f'[ERROR] {result.stderr}', file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
        action_status(relay_filter)

    print('✅ Relays started.')


def action_stop(relay_filter):
    """Stops the specified relay containers."""
    print('🛑 Stopping Nostr relays...')
    if relay_filter == 'all':
        result = _run_compose(['stop'])
    else:
        result = _run_compose(['stop', relay_filter])
    print(result.stdout)
    if result.returncode != 0:
        print(f'[ERROR] {result.stderr}', file=sys.stderr)
        sys.exit(1)
    print('✅ Relays stopped.')


def action_restart(relay_filter, confirmed=False):
    """Restarts the relays."""
    action_stop(relay_filter)
    time.sleep(2)
    action_start(relay_filter, confirmed)


def action_status(relay_filter):
    """Displays the status of the relay containers."""
    result = _run_compose(['ps', '--format', 'json'])
    if result.returncode != 0:
        print(f'[ERROR] {result.stderr}', file=sys.stderr)
        sys.exit(1)

    lines = result.stdout.strip().split('\n')
    containers = []
    for line in lines:
        if line.strip():
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not containers:
        print('⚠️  No Nostr relay containers found.')
        return

    print(f'\n{"Container":25} {"Status":15} {"Ports":15} {"Name":20}')
    print('-' * 75)
    for c in containers:
        cname = c.get('Name', '?')
        # Check if the name matches the filter
        if relay_filter != 'all' and relay_filter not in cname:
            continue
        status = c.get('Status', '?').split(' ')[0] if c.get('Status') else 'unknown'
        ports = c.get('Publishers', '?')
        port_str = ''
        if isinstance(ports, list):
            port_str = ', '.join(
                [f"{p.get('PublishedPort', '?')}->{p.get('TargetPort', '?')}" for p in ports]
            ) if ports else 'none'
        else:
            port_str = str(ports)[:14]
        print(f'{cname[:24]:25} {status[:14]:15} {port_str[:14]:15} '
              f'{c.get("Service", "?"):20}')
    print()


def action_logs(relay_filter, lines):
    """Displays logs of the relay containers."""
    if relay_filter == 'all':
        result = _run_compose(['logs', '--tail', str(lines), '-t'])
    else:
        result = _run_compose(['logs', '--tail', str(lines), '-t', relay_filter])
    print(result.stdout)
    if result.returncode != 0:
        print(f'[ERROR] {result.stderr}', file=sys.stderr)


def action_clean(relay_filter):
    """Deletes relay data (resets volumes)."""
    print('⚠️  Deleting relay data...')
    if relay_filter == 'all':
        # Stop containers and delete volumes
        _run_compose(['down', '-v'])
        print('✅ All relay volumes deleted.')
    else:
        # Single relay: stop container, find and delete volume
        volume_name = f'nostr_memory_{relay_filter}_data'
        _run_compose(['stop', relay_filter])
        subprocess.run(['docker', 'volume', 'rm', volume_name],
                       capture_output=True, text=True)
        print(f'✅ Volume {volume_name} deleted.')
        # Restart it
        action_start(relay_filter)


def action_test(relay_filter=None):
    """Tests reachability of all relays via curl."""
    print('🔍 Testing relay connectivity...')
    for rname in RELAY_NAMES:
        port = RELAY_PORTS[rname]
        try:
            result = subprocess.run(
                ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
                 f'http://localhost:{port}/'],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip() in ['200', '400']:
                print(f'  ✅ {rname} (Port {port}): Reachable (HTTP {result.stdout.strip()})')
            else:
                print(f'  ⚠️  {rname} (Port {port}): Responded with HTTP {result.stdout.strip()}')
        except Exception as e:
            print(f'  ❌ {rname} (Port {port}): Unreachable – {e}')


def main():
    parser = argparse.ArgumentParser(description='Nostr Relay Manager')
    parser.add_argument('--action', required=True,
                        choices=['start', 'stop', 'restart', 'status',
                                 'logs', 'clean', 'test'],
                        help='Action to execute')
    parser.add_argument('--relay', default='all',
                        help='Relay name (relay1, relay2, relay3, all)')
    parser.add_argument('--lines', type=int, default=50,
                        help='Number of lines for logs')
    parser.add_argument('--confirm', action='store_true',
                        help='Confirms local starting of relays')
    args = parser.parse_args()

    actions = {
        'start': action_start,
        'stop': action_stop,
        'restart': action_restart,
        'status': action_status,
        'logs': action_logs,
        'clean': action_clean,
        'test': action_test,
    }

    action_func = actions.get(args.action)
    if args.action in ['logs']:
        action_func(args.relay, args.lines)
    elif args.action in ['start', 'restart']:
        action_func(args.relay, args.confirm)
    else:
        action_func(args.relay)


if __name__ == '__main__':
    main()
