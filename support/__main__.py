import argparse
import json
import os
import sqlite3
import sys

from .agent import run
from .store import Store


def api_failure(exc):
    """Report allowlisted diagnostics without rendering SDK request details."""
    status = getattr(exc, 'status_code', None)
    if not isinstance(status, int):
        status = getattr(exc, 'code', None)
    if not isinstance(status, int):
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None)
    hints = {400: 'Invalid API request or key; check key validity and SDK compatibility.',
             401: 'Authentication failed; check your replacement GEMINI_API_KEY.',
             403: 'Access denied; check key restrictions and model access.',
             404: 'Model or saved interaction unavailable; try a new session.',
             429: 'Quota or rate limit reached; check your Gemini quota.'}
    if isinstance(status, int) and 100 <= status <= 599:
        detail = f'HTTP {status}. ' + hints.get(status, 'Gemini service request failed; retry later.')
    else:
        import httpx
        if isinstance(exc, httpx.TimeoutException):
            detail = 'Network timeout; check connectivity and retry later.'
        elif isinstance(exc, httpx.TransportError):
            detail = 'Network connection failed; check connectivity, proxy, and TLS settings.'
        else:
            detail = 'Check connectivity, model access, key, and quota.'
    return 'Gemini request failed. ' + detail + ' Inspect requests before retrying.'


def main():
    # Windows redirected output may default to a legacy code page; Gemini can
    # return currency symbols and other Unicode text.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Fictional order support; refunds are local simulations.')
    parser.add_argument('--db', default='data/support.db')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('seed')
    ask = sub.add_parser('ask')
    ask.add_argument('prompt')
    ask.add_argument('--session', default='demo')
    sub.add_parser('requests')
    for command in ('inspect', 'approve', 'deny'):
        action = sub.add_parser(command)
        action.add_argument('request_id')
    args = parser.parse_args()
    store = Store(args.db)
    try:
        if args.command == 'seed':
            result = store.seed()
        elif args.command == 'requests':
            result = [dict(row) for row in store.db.execute('SELECT * FROM requests ORDER BY rowid')]
        elif args.command == 'inspect':
            result = store.request(args.request_id)
        elif args.command in ('approve', 'deny'):
            request = store.request(args.request_id)
            print(json.dumps(request, indent=2))
            if request['state'] == 'pending':
                expected = f'{args.command.upper()} {args.request_id}'
                if input(f'Type {expected} to confirm: ').strip() != expected:
                    raise ValueError('Confirmation did not match; no decision recorded')
            result = store.decide(args.request_id, args.command == 'approve')
        else:
            key = os.environ.get('GEMINI_API_KEY', '').strip()
            if not key:
                raise ValueError('Set GEMINI_API_KEY before using ask')
            from google import genai
            # The pinned Interactions SDK maps attempts=1 to one transport retry.
            with genai.Client(api_key=key, http_options={'retry_options': {'attempts': 1}}) as client:
                result = run(client, store, args.prompt, args.session,
                             emit=lambda text: print(text.replace(key, '[REDACTED]')))
        output = result if isinstance(result, str) else json.dumps(result, indent=2)
        key = os.environ.get('GEMINI_API_KEY', '').strip()
        print(output.replace(key, '[REDACTED]') if key else output)
    except (ValueError, sqlite3.Error) as exc:
        key = os.environ.get('GEMINI_API_KEY', '').strip()
        message = str(exc).replace(key, '[REDACTED]') if key else str(exc)
        raise SystemExit(message) from None
    except Exception as exc:
        # SDK errors can include request details; never print the raw exception.
        raise SystemExit(api_failure(exc)) from None
    finally:
        store.close()


if __name__ == '__main__':
    main()
