#!/usr/bin/env python3
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

"""
Hermes Sub-Agent Execution Wrapper.

Allows the edge agent to spawn autonomous sub-agents via the 'hermes' command-line interface.
Loads settings dynamically from the environment or central .env file.
"""

import argparse
import os
import subprocess
import sys


def load_dotenv():
    """Load environment variables from the central workspace .env if not already set."""
    # Find .env relative to this script: src/bob_edge/skills/hermes_agent/scripts/run_agent.py
    # Up 4 levels: skills, hermes_agent, scripts, run_agent.py -> bob_edge root
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.abspath(os.path.join(base_dir, '..', '..', '..', '.env'))

    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = val


def run_hermes(prompt: str, model: str = None, yolo: bool = True) -> int:
    """
    Execute the hermes sub-agent with the given prompt.

    :param prompt: The task instruction.
    :param model: Optional override for the model name.
    :param yolo: Whether to run with --yolo to bypass dangerous prompts.
    :return: Exit code.
    """
    # Build command list
    cmd = ['hermes', '-z', prompt]
    if yolo:
        cmd.append('--yolo')
    if model:
        cmd.extend(['--model', model])

    # Propagate crucial environment variables
    # (Since config.yaml references ${HERMES_MODEL}, ${HERMES_BASE_URL}, ${HERMES_API_KEY})
    env = os.environ.copy()

    # Log execution settings
    model_name = env.get('HERMES_MODEL', 'gemma-4-26B-A4B-it-UD')
    base_url = env.get('HERMES_BASE_URL', 'http://192.168.1.9:8022/v1')
    print('[*] Starting Hermes Sub-Agent...')
    print(f'[*] Model: {model_name}')
    print(f'[*] Base URL: {base_url}')
    print(f'[*] Task: {prompt}')
    print('--------------------------------------------------')

    try:
        # Run process and pipe output live
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )

        # Stream output to stdout in real-time
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()

        process.wait()
        return process.returncode

    except FileNotFoundError:
        print("[!] Error: 'hermes' command not found on PATH.", file=sys.stderr)
        print('[!] Verify hermes-agent is installed in the container.', file=sys.stderr)
        return 127
    except Exception as e:
        print(f'[!] Exception during hermes execution: {e}', file=sys.stderr)
        return 1


def main():
    """CLI entry point for the Hermes agent skill."""
    parser = argparse.ArgumentParser(description='Hermes Agent Skill Wrapper')
    parser.add_argument('prompt', help='Instruction/Task for the Hermes sub-agent')
    parser.add_argument('--model', help='Override default model name (HERMES_MODEL)')
    parser.add_argument(
        '--no-yolo',
        action='store_true',
        help='Disable YOLO mode (will prompt for dangerous actions)'
    )

    args = parser.parse_args()

    # Load central configuration
    load_dotenv()

    # Execute and exit with the return code
    exit_code = run_hermes(
        prompt=args.prompt,
        model=args.model,
        yolo=not args.no_yolo
    )
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
