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

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def get_redis_client():
    try:
        import redis
        redis_host = os.environ.get('REDIS_HOST', 'agent-redis')
        redis_port = int(os.environ.get('REDIS_PORT', 6379))
        return redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)
    except ImportError:
        print(
            'Error: The "redis" python package is not installed. Please add it to your env.',
            file=sys.stderr
        )
        sys.exit(1)


def scratchpad_write(agent_id, data):
    r = get_redis_client()
    key = f'scratchpad:{agent_id}'
    # Expire after 24 hours (86400 seconds)
    r.set(key, data, ex=86400)
    print(f'Successfully wrote to scratchpad for agent "{agent_id}".')


def scratchpad_read(agent_id):
    r = get_redis_client()
    key = f'scratchpad:{agent_id}'
    val = r.get(key)
    if val is None:
        print(f'No scratchpad found for agent "{agent_id}".')
        try:
            state_keys = r.keys('state:now:*')
            if state_keys:
                categories = [k.split(':')[-1] for k in state_keys]
                print('\n[HINT] Active system states are available in Redis!')
                print('You can read them using:')
                for cat in categories:
                    print(f'  --action get_state --category {cat}')
        except Exception:
            pass
    else:
        print(val)


def get_state(category):
    r = get_redis_client()
    key = f'state:now:{category}'
    val = r.get(key)
    if val is None:
        print(f'No current state found for category "{category}".')
    else:
        print(val)


def get_history(category, limit=10):
    r = get_redis_client()
    key = f'state:history:{category}'
    vals = r.lrange(key, 0, limit - 1)
    if not vals:
        print(f'No history found for category "{category}".')
    else:
        parsed_vals = []
        for v in vals:
            try:
                parsed_vals.append(json.loads(v))
            except Exception:
                parsed_vals.append(v)
        print(json.dumps(parsed_vals, indent=2))


def get_couchdb_auth_header():
    import base64
    auth_str = f'admin:{os.environ.get("COUCHDB_PASSWORD", "agentsecret")}'
    return f'Basic {base64.b64encode(auth_str.encode("ascii")).decode("ascii")}'


def couchdb_store(db_name, doc_id, data_str):
    base_url = os.environ.get('COUCHDB_URL', 'http://agent-couchdb:5984').rstrip('/')
    url = f'{base_url}/{db_name}/{doc_id}'
    db_url = f'{base_url}/{db_name}'
    auth_header = get_couchdb_auth_header()

    try:
        # First check if db exists, if not create it
        try:
            req_db = urllib.request.Request(db_url, method='PUT')
            req_db.add_header('Authorization', auth_header)
            urllib.request.urlopen(req_db)
        except urllib.error.HTTPError as e:
            if e.code != 412:  # 412 means DB already exists
                pass

        # Now get the latest rev if doc exists
        rev = None
        try:
            req_get = urllib.request.Request(url)
            req_get.add_header('Authorization', auth_header)
            res = urllib.request.urlopen(req_get)
            existing = json.loads(res.read())
            rev = existing.get('_rev')
        except urllib.error.HTTPError:
            pass  # Doc doesn't exist yet

        doc = json.loads(data_str)
        if rev:
            doc['_rev'] = rev

        req = urllib.request.Request(
            url,
            data=json.dumps(doc).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='PUT'
        )
        req.add_header('Authorization', auth_header)
        res = urllib.request.urlopen(req)
        print(f"Stored successfully in CouchDB: {res.read().decode('utf-8')}")
    except Exception as e:
        print(f'Failed to store in CouchDB: {e}', file=sys.stderr)
        sys.exit(1)


def couchdb_fetch(db_name, doc_id):
    base_url = os.environ.get('COUCHDB_URL', 'http://agent-couchdb:5984').rstrip('/')
    url = f'{base_url}/{db_name}/{doc_id}'
    try:
        req = urllib.request.Request(url)
        req.add_header('Authorization', get_couchdb_auth_header())
        res = urllib.request.urlopen(req)
        print(res.read().decode('utf-8'))
    except Exception as e:
        print(f'Failed to fetch from CouchDB: {e}', file=sys.stderr)
        sys.exit(1)


def qdrant_store(collection, doc_id, data_str):
    try:
        from qdrant_client import QdrantClient
        qdrant_url = os.environ.get('QDRANT_URL', 'http://agent-qdrant:6333')
        client = QdrantClient(url=qdrant_url)

        # client.add() automatically embeds the documents using FastEmbed
        client.add(
            collection_name=collection,
            documents=[data_str],
            ids=[doc_id]
        )
        print(
            f'Successfully embedded and stored document {doc_id} '
            f'in Qdrant collection "{collection}".'
        )
    except Exception as e:
        print(f'Failed to store in Qdrant: {e}', file=sys.stderr)
        sys.exit(1)


def qdrant_search(collection, data_str):
    try:
        from qdrant_client import QdrantClient
        qdrant_url = os.environ.get('QDRANT_URL', 'http://agent-qdrant:6333')
        client = QdrantClient(url=qdrant_url)

        # client.query() automatically embeds the query text and searches
        results = client.query(
            collection_name=collection,
            query_text=data_str,
            limit=3
        )

        if not results:
            print(f'No semantic matches found in collection "{collection}".')
            return

        print(f'Top {len(results)} matches from Qdrant:')
        for r in results:
            print(f' - ID: {r.id} (Score: {r.score:.3f})')
            print(f'   Content: {r.document}')

    except Exception as e:
        print(f'Failed to search Qdrant: {e}', file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Memory Manager Tool')
    parser.add_argument('--action', required=True, choices=[
        'scratchpad_write', 'scratchpad_read',
        'couchdb_store', 'couchdb_fetch',
        'qdrant_store', 'qdrant_search',
        'get_state', 'get_history'
    ])
    parser.add_argument('--agent-id', help='Target Agent ID for scratchpad (defaults to self)')
    parser.add_argument('--data', help='Data to store or query')
    parser.add_argument('--db', help='CouchDB database name')
    parser.add_argument('--doc-id', help='CouchDB document ID')
    parser.add_argument('--collection', help='Qdrant collection name')
    parser.add_argument('--category', help='Category for system state operations (e.g. vision)')
    parser.add_argument('--limit', type=int, default=10, help='Limit for get_history logs')

    args = parser.parse_args()

    # Determine Agent ID
    target_agent_id = args.agent_id
    if not target_agent_id:
        # Fallback to the environment variable set in compose
        target_agent_id = os.environ.get('AGENT_ID', 'main_agent')

    if args.action == 'scratchpad_write':
        if not args.data:
            print('Error: --data is required for scratchpad_write', file=sys.stderr)
            sys.exit(1)
        scratchpad_write(target_agent_id, args.data)

    elif args.action == 'scratchpad_read':
        scratchpad_read(target_agent_id)

    elif args.action == 'couchdb_store':
        if not args.db or not args.doc_id or not args.data:
            print(
                'Error: --db, --doc-id, and --data are required for couchdb_store',
                file=sys.stderr
            )
            sys.exit(1)
        couchdb_store(args.db, args.doc_id, args.data)

    elif args.action == 'couchdb_fetch':
        if not args.db or not args.doc_id:
            print('Error: --db and --doc-id are required for couchdb_fetch', file=sys.stderr)
            sys.exit(1)
        couchdb_fetch(args.db, args.doc_id)

    elif args.action == 'qdrant_store':
        if not args.collection or not args.doc_id or not args.data:
            print(
                'Error: --collection, --doc-id, and --data are required for qdrant_store',
                file=sys.stderr
            )
            sys.exit(1)
        # We need a numeric ID or UUID string for Qdrant.
        # Since doc_id comes as string, we'll try to convert it to int, otherwise pass as string
        try:
            doc_id = int(args.doc_id)
        except ValueError:
            doc_id = args.doc_id

        qdrant_store(args.collection, doc_id, args.data)

    elif args.action == 'qdrant_search':
        if not args.collection or not args.data:
            print('Error: --collection and --data are required for qdrant_search', file=sys.stderr)
            sys.exit(1)
        qdrant_search(args.collection, args.data)

    elif args.action == 'get_state':
        if not args.category:
            print('Error: --category is required for get_state', file=sys.stderr)
            sys.exit(1)
        get_state(args.category)

    elif args.action == 'get_history':
        if not args.category:
            print('Error: --category is required for get_history', file=sys.stderr)
            sys.exit(1)
        get_history(args.category, args.limit)


if __name__ == '__main__':
    main()
