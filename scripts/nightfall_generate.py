#!/usr/bin/env python3
import json, urllib.request, os

MCP_URL = os.environ.get('OMBRE_MCP_URL', 'http://localhost:8000/mcp')

def call_mcp(method, params, session_id=None):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    if session_id:
        headers['mcp-session-id'] = session_id
    payload = json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1}).encode()
    req = urllib.request.Request(MCP_URL, data=payload, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=60) as r:
        resp_headers = dict(r.headers)
        body = r.read().decode()
    for line in body.splitlines():
        if line.startswith('data: '):
            return json.loads(line[6:]), resp_headers
    return json.loads(body), resp_headers

result, headers = call_mcp('initialize', {
    'protocolVersion': '2024-11-05', 'capabilities': {},
    'clientInfo': {'name': 'nightfall-cron', 'version': '1.0'}
})
sid = headers.get('mcp-session-id') or headers.get('Mcp-Session-Id')

result, _ = call_mcp('tools/call', {'name': 'night_fall', 'arguments': {'action': 'generate'}}, sid)
content = result.get('result', {}).get('content', [])
text = ' '.join(c.get('text', '') for c in content if isinstance(c, dict))
print(text or 'no output')
