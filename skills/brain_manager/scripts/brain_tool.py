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

import os


def get_env_vars():
    """Get environment variables, trying to read from .env file if not set."""
    vars_dict = {
        'chat': os.getenv('ORCHESTRATOR_MODEL_CHAT'),
        'reasoner': os.getenv('ORCHESTRATOR_MODEL_REASONER')
    }

    # Try to read .env file if vars are missing
    if not vars_dict['chat'] or not vars_dict['reasoner']:
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if '=' in line and not line.strip().startswith('#'):
                        key, val = line.strip().split('=', 1)
                        val = val.strip('"').strip("'")
                        if key == 'ORCHESTRATOR_MODEL_CHAT' and not vars_dict['chat']:
                            vars_dict['chat'] = val
                        elif key == 'ORCHESTRATOR_MODEL_REASONER' and not vars_dict['reasoner']:
                            vars_dict['reasoner'] = val
    return vars_dict


def get_available_models():
    """
    Check environment and .env for configured LLM models.

    Returns a formatted report for the agent.
    """
    vars_dict = get_env_vars()

    chat = vars_dict['chat']
    reasoner = vars_dict['reasoner']

    report = 'AVAILABLE LLM MODELS FOR BRAIN OPTIMIZATION:\n'
    report += '-------------------------------------------\n'

    if chat:
        report += 'MODE: "chat" (Fast Interaction)\n'
        report += f'MODEL_NAME: {chat}\n'
        report += 'PURPOSE: Default mode for standard conversation and simple tasks.\n\n'
    else:
        report += 'MODE: "chat" -> [ERROR] Not configured in environment.\n\n'

    if reasoner:
        report += 'MODE: "reasoner" (Deep Logic)\n'
        report += f'MODEL_NAME: {reasoner}\n'
        report += 'PURPOSE: Use this for complex coding, debugging, and planning.\n'
    else:
        report += 'MODE: "reasoner" -> [NOT_AVAILABLE] No reasoning model configured.\n'

    report += '-------------------------------------------\n'
    report += 'INSTRUCTION: Copy the MODEL_NAME and use the "set_parameter" tool.'

    return report


def main():
    """Execute the main entry point for the brain management tool."""
    print(get_available_models())


if __name__ == '__main__':
    main()
