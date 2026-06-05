#!/usr/bin/env python3
"""
Nostr Memory Tool – Decentralized agent memory via Nostr protocol.

Enables storing, searching, and retrieving agent memories
as signed Nostr events on 3 local relays.

Usage:
    python3 nostr_memory_tool.py --action store --kind 5000 --content '{"msg": "hello"}'
    python3 nostr_memory_tool.py --action search --kind 5000 --limit 5
    python3 nostr_memory_tool.py --action get_status
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_RELAYS = [
    'ws://localhost:8781',
    'ws://localhost:8782',
    'ws://localhost:8783',
]

# Agent Memory Event Kinds
KIND_TEXT_NOTE = 1
KIND_AGENT_MEMORY = 5000       # Structured Agent Memory
KIND_AGENT_STATE = 30000       # Replaceable Agent State (parameterized)
KIND_AGENT_LOG = 5001          # System logs / Event log
KIND_AGENT_DIALOG = 5002       # Conversation history / Dialog context
KIND_DELETION = 5              # Deletion event


# ---------------------------------------------------------------------------
# Nostr Client (asynchronous, using nostr-sdk)
# ---------------------------------------------------------------------------

class NostrMemoryClient:
    """Wraps the nostr-sdk client for agent memory operations."""

    def __init__(self, relays=None, secret_key=None):
        self.relays = relays or DEFAULT_RELAYS
        self._secret_key = secret_key or os.environ.get('NOSTR_AGENT_SECRET', '')
        self._keys = None
        self._client = None

    def _ensure_keys(self):
        """Ensure that a keypair exists (generate or load)."""
        if self._keys is not None:
            return self._keys

        try:
            from nostr_sdk import Keys, SecretKey
        except ImportError:
            print('[ERROR] nostr-sdk not installed. Run: pip install nostr-sdk',
                  file=sys.stderr)
            sys.exit(1)

        if self._secret_key:
            try:
                secret = SecretKey.from_hex(self._secret_key)
                self._keys = Keys.from_secret_key(secret)
                print(f'[INFO] Agent Public Key: {self._keys.public_key().to_bech32()}',
                      file=sys.stderr)
            except Exception as e:
                print(f'[ERROR] Invalid Secret Key: {e}', file=sys.stderr)
                sys.exit(1)
        else:
            # No key present => generate and output
            self._keys = Keys.generate()
            secret_hex = self._keys.secret_key().to_hex()
            pub_bech32 = self._keys.public_key().to_bech32()
            print(f'[INFO] 🔑 New keypair generated!', file=sys.stderr)
            print(f'[INFO] Public Key (npub): {pub_bech32}', file=sys.stderr)
            print(f'[INFO] Secret Key (Hex):  {secret_hex}', file=sys.stderr)
            print(f'[INFO] Set NOSTR_AGENT_SECRET=... for a persistent identity.',
                  file=sys.stderr)

        return self._keys

    async def _get_client(self):
        """Initializes or returns the nostr-sdk client."""
        if self._client is not None:
            return self._client

        try:
            from nostr_sdk import Client, NostrSigner
        except ImportError:
            print('[ERROR] nostr-sdk not installed.', file=sys.stderr)
            sys.exit(1)

        keys = self._ensure_keys()
        signer = NostrSigner.keys(keys)
        client = Client(signer)

        from nostr_sdk import RelayUrl
        for relay_url in self.relays:
            await client.add_relay(RelayUrl.parse(relay_url))

        await client.connect()
        self._client = client
        return client

    async def store_event(self, kind: int, content: str, tags: list = None):
        """
        Creates and sends a signed Nostr event to all relays.

        Args:
            kind: Nostr event kind (1, 5000, 30000, ...)
            content: JSON string or text
            tags: List of tags, e.g., [["t", "ros2"], ["d", "unique_id"]]

        Returns:
            Event ID (hex) on success, None on error
        """
        try:
            from nostr_sdk import Tag, Kind as NKind, EventBuilder
        except ImportError:
            print('[ERROR] nostr-sdk not installed.', file=sys.stderr)
            sys.exit(1)

        client = await self._get_client()
        tags = tags or []

        # Convert Python tags to nostr-sdk Tag objects
        sdk_tags = []
        for t in tags:
            if len(t) >= 2:
                sdk_tags.append(Tag.parse([t[0], t[1]]))

        # Build, sign and send event
        keys = self._ensure_keys()
        event = EventBuilder(NKind(kind), content).tags(sdk_tags).sign_with_keys(keys)
        await client.send_event(event)

        event_id_hex = event.id().to_hex()
        print(f'✅ Event saved | Kind: {kind} | ID: {event_id_hex[:16]}...')

        return event_id_hex

    async def fetch_events(self, kind: int = None, limit: int = 10,
                           since: int = 0, authors: list = None):
        """
        Retrieves events from relays (newest first).

        Args:
            kind: Filter for specific event kind
            limit: Maximum number of events
            since: Unix timestamp, only newer events
            authors: List of public keys (hex) of the authors

        Returns:
            List of event dicts
        """
        try:
            from nostr_sdk import Filter, Kind as NKind
        except ImportError as e:
            print(f'[ERROR] nostr-sdk not installed. Details: {e}', file=sys.stderr)
            sys.exit(1)

        client = await self._get_client()

        # Build filter
        sk_filter = Filter().limit(limit)
        if kind is not None:
            sk_filter = sk_filter.kind(NKind(kind))
        if since > 0:
            sk_filter = sk_filter.since(since)
        if authors:
            sk_filter = sk_filter.authors(authors)

        # Start subscription, collect events
        events = await client.fetch_events(sk_filter, timedelta(seconds=5))

        results = []
        for event in events.to_vec():
            results.append({
                'id': event.id().to_hex(),
                'pubkey': event.author().to_hex(),
                'created_at': event.created_at().as_secs(),
                'kind': event.kind().as_u16(),
                'tags': [t.as_vec() for t in event.tags().to_vec()],
                'content': event.content(),
            })

        # Sort descending by created_at (newest first)
        results.sort(key=lambda e: e['created_at'], reverse=True)

        return results

    async def get_agent_state(self):
        """
        Retrieves the current agent status (Kind 30000).
        Returns the newest status event.
        """
        events = await self.fetch_events(kind=KIND_AGENT_STATE, limit=1)
        if events:
            return json.loads(events[0]['content']) if events[0]['content'] else {}
        return {}

    async def set_agent_state(self, state_dict: dict):
        """
        Stores the agent status (Kind 30000, replaceable).
        The 'd' tag ensures that old states are overwritten.
        """
        content = json.dumps(state_dict, ensure_ascii=False)
        tags = [['d', 'agent_state']]
        return await self.store_event(KIND_AGENT_STATE, content, tags)

    async def delete_event(self, event_id_hex: str):
        """
        Sends a deletion event (Kind 5) for a specific event ID.
        """
        content = json.dumps([event_id_hex])
        tags = [['e', event_id_hex]]
        return await self.store_event(KIND_DELETION, content, tags)

    async def disconnect(self):
        """Disconnect WebSocket connections."""
        if self._client:
            await self._client.disconnect()
            print('[INFO] Connections disconnected.', file=sys.stderr)

    async def list_keys_info(self):
        """Displays the current key information."""
        keys = self._ensure_keys()
        pub_hex = keys.public_key().to_hex()
        pub_npub = keys.public_key().to_bech32()
        print(f'Public Key (Hex):  {pub_hex}')
        print(f'Public Key (npub): {pub_npub}')
        if self._secret_key:
            print(f'Secret Key (Hex):  {self._secret_key[:8]}... (configured)')
        else:
            print('⚠️  No Secret Key set – temporary key.')


# ---------------------------------------------------------------------------
# CLI Arguments & Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description='Nostr Memory Tool – Decentralized Agent Memory'
    )
    parser.add_argument('--action', required=True,
                        choices=['store', 'get', 'search', 'delete',
                                 'set_status', 'get_status', 'list_keys'],
                        help='Action to execute')
    parser.add_argument('--kind', type=int, default=KIND_AGENT_MEMORY,
                        help=f'Nostr Event Kind (default: {KIND_AGENT_MEMORY})')
    parser.add_argument('--content', default='',
                        help='Event content (JSON string or text)')
    parser.add_argument('--event-id', default='',
                        help='Event ID (hex) to retrieve/delete')
    parser.add_argument('--tags', default='',
                        help='Comma-separated tags, e.g. "ros2,memory,evolution"')
    parser.add_argument('--limit', type=int, default=10,
                        help='Maximum number of matches in search')
    parser.add_argument('--since', type=int, default=0,
                        help='Unix timestamp – only newer events')
    parser.add_argument('--relays', default='',
                        help='Comma-separated relay URLs (Override)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON (for machine processing)')

    return parser.parse_args()


def _build_tags(tag_str: str, kind: int) -> list:
    """Builds Nostr tags from comma-separated string."""
    tags = []
    if tag_str:
        for t in tag_str.split(','):
            t = t.strip()
            if t:
                tags.append(['t', t])
    # For Kind 30000: d-tag for replaceability
    if kind == KIND_AGENT_STATE:
        if not any(t[0] == 'd' for t in tags):
            tags.append(['d', 'agent_state'])
    return tags


def _format_event(ev: dict, json_output: bool = False) -> str:
    """Formats an event for output."""
    if json_output:
        return json.dumps(ev, ensure_ascii=False, indent=2)

    created = datetime.fromtimestamp(ev['created_at'], tz=timezone.utc)
    content_preview = ev['content'][:120] + '...' if len(ev['content']) > 120 else ev['content']
    return (
        f'┌─ Event {ev["id"][:16]}...\n'
        f'│  Kind:    {ev["kind"]}\n'
        f'│  From:    {ev["pubkey"][:16]}...\n'
        f'│  Time:    {created.strftime("%Y-%m-%d %H:%M:%S UTC")}\n'
        f'│  Tags:    {ev["tags"]}\n'
        f'│  Content: {content_preview}\n'
        f'└─'
    )


async def main_async():
    args = parse_args()

    # Configure relays
    relays = DEFAULT_RELAYS
    if args.relays:
        relays = [r.strip() for r in args.relays.split(',') if r.strip()]

    # Secret Key from environment
    secret_key = os.environ.get('NOSTR_AGENT_SECRET', '')

    client = NostrMemoryClient(relays=relays, secret_key=secret_key)

    try:
        if args.action == 'store':
            tags = _build_tags(args.tags, args.kind)
            event_id = await client.store_event(args.kind, args.content, tags)
            if event_id:
                print(f'\nEvent-ID: {event_id}')

        elif args.action == 'get':
            if not args.event_id:
                print('[ERROR] --event-id is required for get', file=sys.stderr)
                sys.exit(1)
            # Search for specific ID (via filter with ID)
            try:
                from nostr_sdk import Filter, EventId
                c = await client._get_client()
                ev_filter = Filter().id(EventId.from_hex(args.event_id)).limit(1)
                events = await c.fetch_events(ev_filter, timedelta(seconds=5))
                results = []
                for event in events.to_vec():
                    results.append({
                        'id': event.id().to_hex(),
                        'pubkey': event.author().to_hex(),
                        'created_at': event.created_at().as_secs(),
                        'kind': event.kind().as_u16(),
                        'tags': [t.as_vec() for t in event.tags().to_vec()],
                        'content': event.content(),
                    })
                if results:
                    print(_format_event(results[0], args.json))
                else:
                    print(f'⚠️  No event with ID {args.event_id[:16]}... found.')
            except Exception as e:
                print(f'[ERROR] During retrieval: {e}', file=sys.stderr)
                sys.exit(1)

        elif args.action == 'search':
            events = await client.fetch_events(
                kind=args.kind,
                limit=args.limit,
                since=args.since
            )
            if not events:
                print(f'🔍 No events of kind {args.kind} found.')
            else:
                print(f'🔍 Found {len(events)} event(s) of kind {args.kind}:\n')
                for ev in events:
                    print(_format_event(ev, args.json))
                    print()

        elif args.action == 'delete':
            if not args.event_id:
                print('[ERROR] --event-id is required for delete', file=sys.stderr)
                sys.exit(1)
            await client.delete_event(args.event_id)
            print(f'🗑️  Deletion event for {args.event_id[:16]}... sent.')

        elif args.action == 'set_status':
            try:
                content_json = json.loads(args.content) if args.content else {}
            except json.JSONDecodeError:
                content_json = {'message': args.content}
            # Automatically add timestamp
            content_json['_updated_at'] = int(time.time())
            await client.set_agent_state(content_json)
            print('✅ Agent status updated.')

        elif args.action == 'get_status':
            state = await client.get_agent_state()
            if state:
                if args.json:
                    print(json.dumps(state, ensure_ascii=False, indent=2))
                else:
                    print('📋 Current agent status:')
                    for key, val in state.items():
                        print(f'  {key}: {val}')
            else:
                print('ℹ️  No agent status stored.')

        elif args.action == 'list_keys':
            await client.list_keys_info()

    finally:
        await client.disconnect()


def main():
    asyncio.run(main_async())


if __name__ == '__main__':
    main()
