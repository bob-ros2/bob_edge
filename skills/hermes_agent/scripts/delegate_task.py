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
Hermes Sub-Agent Task Delegation Wrapper.

Spawns isolated parent agent to orchestrate and delegate parallel sub-tasks
using the internal delegate_task tool, formatting and passing task definitions in JSON.
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


def run_delegate_task(
    tasks_payload: dict,
    system_prompt: str = None,
    model: str = None,
    yolo: bool = True,
    identifier: str = 'delegate',
    timeout: float = None,
    detach: bool = True
) -> int:
    """
    Execute the hermes agent orchestrator with custom system prompt to run delegation tasks.

    :param tasks_payload: A dictionary or list defining the task(s) to delegate.
    :param system_prompt: Optional custom system prompt (SOUL.md) to append/prepend.
    :param model: Optional override for the model name.
    :param yolo: Whether to run with --yolo to bypass dangerous prompts.
    :param identifier: Suffix for task directory.
    :param timeout: Optional execution timeout in seconds.
    :param detach: Whether to double-fork and run the task in the background.
    :return: Exit code.
    """
    # 1. Generate unique task ID and directory
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    random_hex = secrets.token_hex(3)
    task_id = f'task_{timestamp_str}_{identifier}_{random_hex}'

    # Ensure profile name is valid
    profile_name = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in task_id)

    task_dir = os.path.expanduser(f'~/agent/hermes/{profile_name}')
    os.makedirs(task_dir, exist_ok=True)
    os.chdir(task_dir)

    # 2. Prep environment and load fallback variables
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONIOENCODING'] = 'UTF-8'
    # Force subagent sessions and workspace hints to run inside the task directory
    env['TERMINAL_CWD'] = task_dir
    model_name = model or env.get('HERMES_MODEL', 'gemma-4-26B-A4B-it-UD')
    base_url = env.get('HERMES_BASE_URL', 'http://192.168.1.9:8022/v1')

    print(f'[*] Spawning orchestrator in isolated profile: {profile_name}')
    print(f'[*] Output directory: {task_dir}')
    print(f'[*] Model: {model_name}')
    print(f'[*] Base URL: {base_url}')
    print('--------------------------------------------------')

    # 3. Create isolated profile by cloning default configuration
    clone_cmd = ['hermes', 'profile', 'create', profile_name, '--clone']
    clone_res = subprocess.run(clone_cmd, capture_output=True, text=True, check=False)
    if clone_res.returncode != 0:
        print(f'[!] Failed to create profile: {clone_res.stderr}', file=sys.stderr)
        return clone_res.returncode

    # 4. Construct orchestrator system prompt
    orchestrator_instructions = (
        "You are a task orchestrator.\n"
        "Your ONLY objective is to execute the delegation tasks specified in the user prompt "
        "using the `delegate_task` tool.\n\n"
        "Instructions:\n"
        "1. Parse the JSON provided in the user prompt.\n"
        "2. If the JSON defines a list of tasks (is a JSON array or has a \"tasks\" key), "
        "call `delegate_task(tasks=[...])` with the tasks.\n"
        "3. If the JSON defines a single task (has \"goal\", \"context\", etc.), "
        "call `delegate_task(goal=goal, context=context, toolsets=toolsets, max_iterations=max_iterations)`.\n"
        "4. Wait for the sub-agent(s) to complete, then return their findings.\n"
        "5. Do not run any other tools.\n"
    )

    if system_prompt:
        full_system_prompt = f"{orchestrator_instructions}\n\nAdditional instructions:\n{system_prompt}"
    else:
        full_system_prompt = orchestrator_instructions

    # 5. Apply custom system prompt (SOUL.md) if provided
    soul_path = os.path.expanduser(f'~/.hermes/profiles/{profile_name}/SOUL.md')
    try:
        with open(soul_path, 'w', encoding='utf-8') as f:
            f.write(full_system_prompt)
        # Copy to output log folder for tracking/reference
        with open(os.path.join(task_dir, 'SOUL.md'), 'w', encoding='utf-8') as f:
            f.write(full_system_prompt)
        print('[*] Applied orchestrator system prompt (SOUL.md)')
    except Exception as e:
        print(f'[!] Failed to write system prompt: {e}', file=sys.stderr)

    # If detach is True, double-fork to run the execution in the background
    if detach:
        try:
            pid = os.fork()
            if pid > 0:
                # Parent prints detachment information and exits immediately
                print(f'[+] Detached delegation to background. PID: {pid}')
                print(f'[+] Monitor progress: tail -f {os.path.join(task_dir, "output.log")}')
                print(f'[+] Final report will be written to: {os.path.join(task_dir, "report.md")}')
                return 0
        except OSError as e:
            print(f'[!] fork #1 failed: {e}', file=sys.stderr)
            return 1

        # Decouple from parent environment
        # Run in task_dir (do not os.chdir('/')) so subagents run in the task CWD
        os.setsid()
        os.umask(0)

        # Do second fork to completely release terminal association
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError as e:
            print(f'[!] fork #2 failed: {e}', file=sys.stderr)
            sys.exit(1)

        # Redirect standard file descriptors to devnull
        sys.stdout.flush()
        sys.stderr.flush()
        si = open(os.devnull, 'r')
        so = open(os.devnull, 'a+')
        se = open(os.devnull, 'a+')
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

    # Now the execution logic starts (runs in the background child process if detach=True, or foreground if detach=False)
    exit_code = 1
    log_file_path = os.path.join(task_dir, 'output.log')
    try:
        # 6. Build and execute the hermes CLI command
        prompt_str = json.dumps(tasks_payload)
        cmd = ['hermes', '-p', profile_name, '-z', prompt_str]
        if yolo:
            cmd.append('--yolo')
        if model:
            cmd.extend(['--model', model])

        start_time = time.time()
        stdout_chunks = []

        try:
            with open(log_file_path, 'w', encoding='utf-8') as log_f:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env
                )

                # Stream output to log file (and stdout/stderr if not detached) in real-time
                while True:
                    # Check for execution timeout
                    if timeout and (time.time() - start_time) > timeout:
                        err_timeout = f'\n[!] Timeout of {timeout}s reached. Terminating orchestrator...\n'
                        log_f.write(err_timeout)
                        log_f.flush()
                        if not detach:
                            sys.stderr.write(err_timeout)
                            sys.stderr.flush()
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        exit_code = 124  # Standard timeout exit code
                        break

                    # Wait for data to be available on stdout or stderr (1.0 second timeout)
                    rlist, _, _ = select.select([process.stdout, process.stderr], [], [], 1.0)
                    
                    if process.stdout in rlist:
                        line = process.stdout.readline()
                        if line:
                            stdout_chunks.append(line)
                            log_f.write(line)
                            log_f.flush()
                            if not detach:
                                sys.stdout.write(line)
                                sys.stdout.flush()

                    if process.stderr in rlist:
                        line = process.stderr.readline()
                        if line:
                            log_f.write(f'[stderr] {line}')
                            log_f.flush()
                            if not detach:
                                sys.stderr.write(line)
                                sys.stderr.flush()

                    # If no data and process exited, break
                    if process.poll() is not None:
                        # Read any remaining output
                        for line in process.stdout:
                            stdout_chunks.append(line)
                            log_f.write(line)
                            if not detach:
                                sys.stdout.write(line)
                        for line in process.stderr:
                            log_f.write(f'[stderr] {line}')
                            if not detach:
                                sys.stderr.write(line)
                        process.wait()
                        exit_code = process.returncode
                        break

        except FileNotFoundError:
            err_msg = "[!] Error: 'hermes' command not found on PATH."
            if not detach:
                print(err_msg, file=sys.stderr)
            with open(log_file_path, 'a', encoding='utf-8') as log_f:
                log_f.write(f'\n{err_msg}\n')
            exit_code = 127
        except Exception as e:
            err_msg = f'[!] Exception during hermes execution: {e}'
            if not detach:
                print(err_msg, file=sys.stderr)
            with open(log_file_path, 'a', encoding='utf-8') as log_f:
                log_f.write(f'\n{err_msg}\n')
            exit_code = 1
        finally:
            # 7. Cleanup: Delete the temporary profile
            delete_cmd = ['hermes', 'profile', 'delete', '-y', profile_name]
            delete_res = subprocess.run(delete_cmd, capture_output=True, text=True, check=False)
            if delete_res.returncode != 0:
                err_msg = f'[!] Warning: Failed to delete profile {profile_name}: {delete_res.stderr.strip()}'
                if not detach:
                    print(err_msg, file=sys.stderr)
                with open(log_file_path, 'a', encoding='utf-8') as log_f:
                    log_f.write(f'\n{err_msg}\n')

        # 8. Save metadata json report
        run_info = {
            'task_id': profile_name,
            'timestamp': datetime.now().isoformat(),
            'tasks': tasks_payload,
            'system_prompt': system_prompt,
            'model': model_name,
            'yolo': yolo,
            'exit_code': exit_code
        }
        try:
            with open(os.path.join(task_dir, 'run_info.json'), 'w', encoding='utf-8') as f:
                json.dump(run_info, f, indent=2)
        except Exception as e:
            if not detach:
                print(f'[!] Failed to write metadata: {e}', file=sys.stderr)

        # 9. Save final report.md
        if exit_code == 0:
            report_content = "".join(stdout_chunks)
        else:
            report_content = (
                f"# Execution Failed\n\n"
                f"Orchestrator exited with non-zero exit code: {exit_code}\n\n"
                f"Please check `output.log` for more details."
            )

        try:
            with open(os.path.join(task_dir, 'report.md'), 'w', encoding='utf-8') as f:
                f.write(report_content)
        except Exception as e:
            if not detach:
                print(f'[!] Failed to write report.md: {e}', file=sys.stderr)

    except Exception as outer_e:
        import traceback
        try:
            with open(log_file_path, 'a', encoding='utf-8') as log_f:
                log_f.write("\n[!] Grandchild process crashed with unexpected exception:\n")
                traceback.print_exc(file=log_f)
        except:
            pass
        exit_code = 1

    if detach:
        sys.exit(exit_code)

    return exit_code


def inject_redirection_instruction(payload: dict | list) -> None:
    """Programmatically append output redirection instructions to each task's context."""
    instruction = (
        "\n\nOutput Redirection Rule: When executing search/crawl scripts or verbose "
        "command-line tools via the terminal tool, redirect their output to files in "
        "the current task/workspace directory (e.g., 'python3 search.py ... > search_results.json') "
        "so that the raw execution data is preserved. Do not output raw webpage/search "
        "JSON directly to the terminal stdout unless requested."
    )

    def process_task(task: dict) -> None:
        if not isinstance(task, dict):
            return
        current_context = task.get("context", "")
        if not current_context:
            task["context"] = instruction.strip()
        else:
            task["context"] = current_context.rstrip() + instruction

    if isinstance(payload, list):
        for t in payload:
            process_task(t)
    elif isinstance(payload, dict):
        if "goal" in payload:
            process_task(payload)
        if "tasks" in payload and isinstance(payload["tasks"], list):
            for t in payload["tasks"]:
                process_task(t)


def main():
    """CLI entry point for the Hermes delegate_task skill."""
    parser = argparse.ArgumentParser(description='Hermes Agent Skill Task Delegation Wrapper')
    parser.add_argument(
        'tasks_json',
        nargs='?',
        default=None,
        help='JSON string or file path containing tasks (list or dict)'
    )
    parser.add_argument(
        '--tasks',
        help='JSON string or file path containing tasks (alternative to positional argument)'
    )
    parser.add_argument('--goal', help='Goal for single task delegation (ignored if tasks JSON is provided)')
    parser.add_argument('--context', help='Context for single task delegation')
    parser.add_argument(
        '--toolsets',
        help='Comma-separated toolsets for single task delegation (e.g. skills,terminal,file)'
    )
    parser.add_argument(
        '--max-iterations',
        type=int,
        help='Max iterations for single task delegation'
    )
    parser.add_argument('--system', help='Custom instructions to append/prepend to orchestrator SOUL.md')
    parser.add_argument('--model', help='Override default model name (HERMES_MODEL)')
    parser.add_argument(
        '--no-yolo',
        action='store_true',
        help='Disable YOLO mode (will prompt for dangerous actions)'
    )
    parser.add_argument(
        '--no-detach',
        action='store_true',
        help='Run in the foreground (blocking mode) instead of detaching to background'
    )
    parser.add_argument(
        '--id',
        default='delegate',
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

    # Resolve tasks payload
    tasks_input = args.tasks or args.tasks_json
    tasks_payload = None

    if tasks_input:
        # Check if tasks_input is a path to a file
        if os.path.exists(tasks_input):
            try:
                with open(tasks_input, 'r', encoding='utf-8') as f:
                    tasks_payload = json.load(f)
            except Exception as e:
                print(f'[!] Failed to parse JSON from file {tasks_input}: {e}', file=sys.stderr)
                sys.exit(1)
        else:
            try:
                tasks_payload = json.loads(tasks_input)
            except Exception as e:
                print(f'[!] Failed to parse tasks JSON string: {e}', file=sys.stderr)
                sys.exit(1)
    elif args.goal:
        # Construct single task dictionary
        task = {"goal": args.goal}
        if args.context:
            task["context"] = args.context
        if args.toolsets:
            task["toolsets"] = [t.strip() for t in args.toolsets.split(',') if t.strip()]
        if args.max_iterations:
            task["max_iterations"] = args.max_iterations
        tasks_payload = task
    else:
        print('[!] Error: You must provide either a tasks JSON payload or a --goal argument.', file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    # Validate tasks_payload structure
    if isinstance(tasks_payload, list):
        for idx, task in enumerate(tasks_payload):
            if not isinstance(task, dict):
                print(f'[!] Error: Task at index {idx} is not an object.', file=sys.stderr)
                sys.exit(1)
            if 'goal' not in task:
                print(f'[!] Error: Task at index {idx} is missing the mandatory "goal" field.', file=sys.stderr)
                sys.exit(1)
    elif isinstance(tasks_payload, dict):
        if 'goal' not in tasks_payload and 'tasks' not in tasks_payload:
            print('[!] Error: Single task object is missing the "goal" field (or "tasks" field).', file=sys.stderr)
            sys.exit(1)
        if 'tasks' in tasks_payload and isinstance(tasks_payload['tasks'], list):
            # Check individual tasks in tasks key
            for idx, task in enumerate(tasks_payload['tasks']):
                if not isinstance(task, dict) or 'goal' not in task:
                    print(f'[!] Error: Subtask at index {idx} in "tasks" list is invalid or missing "goal".', file=sys.stderr)
                    sys.exit(1)
    else:
        print('[!] Error: Invalid tasks payload format. Must be a list of tasks or a task dictionary.', file=sys.stderr)
        sys.exit(1)

    # Inject prompt redirection rules to force saving raw outputs
    inject_redirection_instruction(tasks_payload)

    # Execute and exit with the return code
    exit_code = run_delegate_task(
        tasks_payload=tasks_payload,
        system_prompt=args.system,
        model=args.model,
        yolo=not args.no_yolo,
        identifier=args.id,
        timeout=args.timeout,
        detach=not args.no_detach
    )
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
