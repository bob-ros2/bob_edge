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

"""Crawl and extract web page content using Crawl4AI."""

import argparse
import json
import os
import sys

import requests


def crawl_page(url: str, priority: int = 1) -> str:
    """
    Crawl a webpage using Crawl4AI service.

    :param url: The target webpage URL.
    :param priority: Crawl job priority.
    :return: A JSON string containing results or error.
    """
    # Normalize url protocol
    if not (url.startswith('http://') or url.startswith('https://')):
        url = 'http://' + url

    # Determine endpoint URL
    crawl_url = os.environ.get('MASTER_CRAWL4AI_URL', '').strip()
    if not crawl_url:
        base_url = os.environ.get('CRAWL4AI_BASE_URL', '').strip()
        if base_url:
            crawl_url = base_url.rstrip('/') + '/crawl'
        else:
            crawl_url = 'http://api-gateway:8080/crawl'

    # Ensure URL starts with protocol
    if not (crawl_url.startswith('http://') or crawl_url.startswith('https://')):
        crawl_url = 'http://' + crawl_url

    # Retrieve API key
    api_key = os.environ.get('CRAWL4AI_API_KEY', '').strip()

    headers = {
        'Content-Type': 'application/json'
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    payload = {
        'urls': url,
        'priority': priority
    }

    try:
        # Crawling may take some time, set 45.0s timeout
        response = requests.post(crawl_url, json=payload, headers=headers, timeout=45.0)
        response.raise_for_status()
        data = response.json()

        # Parse standard Crawl4AI list format
        if isinstance(data, dict) and 'results' in data:
            results = data['results']
            if isinstance(results, list) and len(results) > 0:
                result = results[0]
                success = result.get('success', True)
                if not success:
                    err_msg = (
                        result.get('error_message') or
                        'Crawling failed on the service side'
                    )
                    return json.dumps({
                        'status': 'error',
                        'type': 'crawl_failure',
                        'message': err_msg
                    })

                md = result.get('markdown', '')
                if isinstance(md, dict):
                    markdown_content = (
                        md.get('fit_markdown') or
                        md.get('raw_markdown') or
                        str(md)
                    )
                else:
                    markdown_content = str(md)

                metadata = result.get('metadata', {})
                title = metadata.get('title', '') if isinstance(metadata, dict) else ''

                return json.dumps({
                    'status': 'success',
                    'url': result.get('url', url),
                    'title': title,
                    'markdown': markdown_content,
                    'metadata': metadata
                }, ensure_ascii=False, indent=2)

        # Fallback/alternative format (direct result object)
        if isinstance(data, dict):
            # Check for error in direct object
            if not data.get('success', True):
                err_msg = (
                    data.get('error_message') or
                    'Crawling failed on the service side'
                )
                return json.dumps({
                    'status': 'error',
                    'type': 'crawl_failure',
                    'message': err_msg
                })

            md = data.get('markdown', '')
            if md:
                if isinstance(md, dict):
                    markdown_content = (
                        md.get('fit_markdown') or
                        md.get('raw_markdown') or
                        str(md)
                    )
                else:
                    markdown_content = str(md)
                metadata = data.get('metadata', {})
                title = metadata.get('title', '') if isinstance(metadata, dict) else ''
                return json.dumps({
                    'status': 'success',
                    'url': data.get('url', url),
                    'title': title,
                    'markdown': markdown_content,
                    'metadata': metadata
                }, ensure_ascii=False, indent=2)

        return json.dumps({
            'status': 'success',
            'url': url,
            'raw_response': data
        }, ensure_ascii=False, indent=2)

    except requests.exceptions.RequestException as e:
        return json.dumps({'status': 'error', 'type': 'network_error', 'message': str(e)})
    except Exception as e:
        return json.dumps({'status': 'error', 'type': 'system_error', 'message': str(e)})


def main():
    """CLI entrypoint for the crawl skill."""
    parser = argparse.ArgumentParser(description='Crawl webpage via Crawl4AI')
    parser.add_argument('--url', '-u', required=True, help='URL to crawl')
    parser.add_argument('--priority', '-p', type=int, default=1, help='Priority of the job')

    # Handle direct positional arguments for compatibility
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        url = sys.argv[1]
        priority = 1
        if len(sys.argv) > 2:
            try:
                priority = int(sys.argv[2])
            except ValueError:
                pass
        print(crawl_page(url, priority))
        return

    args = parser.parse_args()
    print(crawl_page(args.url, args.priority))


if __name__ == '__main__':
    main()
