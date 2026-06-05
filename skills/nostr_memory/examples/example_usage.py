#!/usr/bin/env python3
"""
Example: Using the Nostr Memory Skill.

Starts relays, stores memories, retrieves them, and displays the status.
"""

import os
import shlex
import subprocess
import sys
import time

# Path to the skill directory (dynamically determined)
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_script(script, args):
    """Executes a skill script."""
    cmd = [sys.executable, f'{SKILL_DIR}/scripts/{script}'] + shlex.split(args)
    print(f'\n$ {" ".join(cmd)}')
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode


def main():
    print('=' * 60)
    print('  Nostr Memory Skill – Example Workflow')
    print('=' * 60)

    # 1. Start relays
    print('\n[1/5] Starting relays...')
    run_script('nostr_relay_manager.py', '--action start --confirm')
    time.sleep(3)

    # 2. Check status
    print('\n[2/5] Checking relay status...')
    run_script('nostr_relay_manager.py', '--action status')

    # 3. Set agent status
    print('\n[3/5] Saving agent status...')
    run_script('nostr_memory_tool.py',
               '--action set_status --content \'{"role": "main_agent", '
               '"mood": "curious", "version": "1.0"}\'')

    # 4. Store a memory
    print('\n[4/5] Saving memory (Kind 5000)...')
    run_script('nostr_memory_tool.py',
               '--action store --kind 5000 '
               '--content \'{"topic": "evolution_plan", '
               '"suggestion": "Introduce Nostr-based memory"}\' '
               '--tags "nostr,memory,evolution"')

    # Wait briefly until events are propagated
    time.sleep(2)

    # 5. Retrieve stored memories
    print('\n[5/5] Searching stored memories...')
    run_script('nostr_memory_tool.py',
               '--action search --kind 5000 --limit 5')

    # 6. Retrieve status
    print('\n[Bonus] Retrieving agent status...')
    run_script('nostr_memory_tool.py',
               '--action get_status')

    print('\n' + '=' * 60)
    print('  Workflow completed.')
    print('  Relays continue running. Stop them with:')
    print('  python3 scripts/nostr_relay_manager.py --action stop')
    print('=' * 60)


if __name__ == '__main__':
    main()
