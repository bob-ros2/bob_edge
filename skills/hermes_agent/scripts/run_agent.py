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

Spawns isolated, configurable sub-agents and records history and metadata.
"""

import argparse
from datetime import datetime
import json
import os
import secrets
import select
import subprocess
import sys
import time


def load_dotenv():
    """Load environment variables from the central workspace .env if not already set."""
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


def run_hermes(
    prompt: str,
    system_prompt: str = None,
    model: str = None,
    yolo: bool = True,
    identifier: str = 'subagent',
    timeout: float = None
) -> int:
    """
    Execute the hermes sub-agent with logging, isolation, and custom system prompt.

    :param prompt: The task instruction.
    :param system_prompt: Optional custom system prompt (SOUL.md).
    :param model: Optional override for the model name.
    :param yolo: Whether to run with --yolo to bypass dangerous prompts.
    :param identifier: Suffix for task directory.
    :param timeout: Optional execution timeout in seconds.
    :return: Exit code.
    """
    # 1. Generate unique task ID and directory
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    random_hex = secrets.token_hex(3)
    task_id = f'task_{timestamp_str}_{identifier}_{random_hex}'

    # Ensure profile name is valid (replace non-alphanumeric/dash/underscore with underscore)
    profile_name = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in task_id)

    task_dir = os.path.expanduser(f'~/agent/hermes/{profile_name}')
    os.makedirs(task_dir, exist_ok=True)

    # 2. Prep environment and load fallback variables
    env = os.environ.copy()
    model_name = model or env.get('HERMES_MODEL', 'gemma-4-26B-A4B-it-UD')
    base_url = env.get('HERMES_BASE_URL', 'http://192.168.1.9:8022/v1')

    print(f'[*] Spawning sub-agent in isolated profile: {profile_name}')
    print(f'[*] Output directory: {task_dir}')
    print(f'[*] Model: {model_name}')
    print(f'[*] Base URL: {base_url}')
    print('--------------------------------------------------')

    # 3. Create isolated profile by cloning default configuration
    # This inherits default api_key and base_url settings
    clone_cmd = ['hermes', 'profile', 'create', profile_name, '--clone']
    clone_res = subprocess.run(clone_cmd, capture_output=True, text=True, check=False)
    if clone_res.returncode != 0:
        print(f'[!] Failed to create profile: {clone_res.stderr}', file=sys.stderr)
        return clone_res.returncode

    # 4. Apply custom system prompt (SOUL.md) if provided
    soul_path = os.path.expanduser(f'~/.hermes/profiles/{profile_name}/SOUL.md')
    if system_prompt:
        try:
            with open(soul_path, 'w', encoding='utf-8') as f:
                f.write(system_prompt)
            # Copy to output log folder for tracking/reference
            with open(os.path.join(task_dir, 'SOUL.md'), 'w', encoding='utf-8') as f:
                f.write(system_prompt)
            print('[*] Applied custom system prompt (SOUL.md)')
        except Exception as e:
            print(f'[!] Failed to write system prompt: {e}', file=sys.stderr)

    # 5. Build and execute the hermes CLI command
    cmd = ['hermes', '-p', profile_name, '-z', prompt]
    if yolo:
        cmd.append('--yolo')
    if model:
        cmd.extend(['--model', model])

    exit_code = 1
    log_file_path = os.path.join(task_dir, 'output.log')
    start_time = time.time()

    try:
        with open(log_file_path, 'w', encoding='utf-8') as log_f:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env
            )

            # Stream output to stdout and log file in real-time with timeout protection
            while True:
                # Check for execution timeout
                if timeout and (time.time() - start_time) > timeout:
                    print(
                        f'\n[!] Timeout of {timeout}s reached. Terminating sub-agent...',
                        file=sys.stderr
                    )
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        print(
                            '[!] Sub-agent failed to terminate gracefully. Killing...',
                            file=sys.stderr
                        )
                        process.kill()
                    exit_code = 124  # Standard timeout exit code
                    break

                # Wait for data to be available on stdout (1.0 second timeout)
                rlist, _, _ = select.select([process.stdout], [], [], 1.0)
                if process.stdout in rlist:
                    line = process.stdout.readline()
                    if not line:
                        # EOF reached
                        process.wait()
                        exit_code = process.returncode
                        break
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    log_f.write(line)
                else:
                    # No data available yet, check if process already exited
                    if process.poll() is not None:
                        process.wait()
                        exit_code = process.returncode
                        break

    except FileNotFoundError:
        print("[!] Error: 'hermes' command not found on PATH.", file=sys.stderr)
        exit_code = 127
    except Exception as e:
        print(f'[!] Exception during hermes execution: {e}', file=sys.stderr)
        exit_code = 1
    finally:
        # 6. Cleanup: Delete the temporary profile
        delete_cmd = ['hermes', 'profile', 'delete', '-y', profile_name]
        delete_res = subprocess.run(delete_cmd, capture_output=True, text=True, check=False)
        if delete_res.returncode != 0:
            print(
                f'[!] Warning: Failed to delete profile {profile_name}: '
                f'{delete_res.stderr.strip()}',
                file=sys.stderr
            )

    # 7. Save metadata json report
    run_info = {
        'task_id': profile_name,
        'timestamp': datetime.now().isoformat(),
        'prompt': prompt,
        'system_prompt': system_prompt,
        'model': model_name,
        'yolo': yolo,
        'exit_code': exit_code
    }
    try:
        with open(os.path.join(task_dir, 'run_info.json'), 'w', encoding='utf-8') as f:
            json.dump(run_info, f, indent=2)
    except Exception as e:
        print(f'[!] Failed to write metadata: {e}', file=sys.stderr)

    return exit_code


def main():
    """CLI entry point for the Hermes agent skill."""
    parser = argparse.ArgumentParser(description='Hermes Agent Skill Wrapper')
    parser.add_argument('prompt', help='Instruction/Task for the Hermes sub-agent')
    parser.add_argument('--system', help='Custom system prompt (SOUL.md) for the sub-agent')
    parser.add_argument('--model', help='Override default model name (HERMES_MODEL)')
    parser.add_argument(
        '--no-yolo',
        action='store_true',
        help='Disable YOLO mode (will prompt for dangerous actions)'
    )
    parser.add_argument(
        '--id',
        default='subagent',
        help='Custom identifier for log folder prefix'
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=None,
        help='Maximum execution time in seconds'
    )

    args = parser.parse_args()

    # Load central configuration
    load_dotenv()

    # Execute and exit with the return code
    exit_code = run_hermes(
        prompt=args.prompt,
        system_prompt=args.system,
        model=args.model,
        yolo=not args.no_yolo,
        identifier=args.id,
        timeout=args.timeout
    )
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
