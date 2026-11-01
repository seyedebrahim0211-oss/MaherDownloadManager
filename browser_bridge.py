"""Authenticated, loopback-only browser bridge for explicitly paired extensions."""
from __future__ import annotations

import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

PORT = 17691
_EXTENSION = re.compile(r'^(chrome-extension|moz-extension|edge-extension)://[A-Za-z0-9_-]+$', re.I)


def start_bridge(manager, port=PORT):
    class Handler(BaseHTTPRequestHandler):
        def _origin(self):
            origin = self.headers.get('Origin','')
            return origin if _EXTENSION.fullmatch(origin) else None

        def _host_valid(self):
            # Prevent DNS rebinding and accidental binding via wildcard Host headers.
            host = self.headers.get('Host','').split(':',1)[0].lower()
            return host in ('127.0.0.1','localhost','[::1]')

        def _authorized(self):
            token = self.headers.get('X-Maher-Token','')
            return bool(self._origin() and self._host_valid() and token and hmac.compare_digest(token, manager.pairing_token))

        def _respond(self, status, obj):
            payload = json.dumps(obj,ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(payload)))
            origin = self._origin()
            if origin and self._host_valid():
                self.send_header('Access-Control-Allow-Origin',origin)
                self.send_header('Vary','Origin')
                self.send_header('Access-Control-Allow-Headers','Content-Type, X-Maher-Token')
                self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            try:self.wfile.write(payload)
            except (BrokenPipeError,ConnectionResetError):pass

        def do_OPTIONS(self):
            if not self._origin() or not self._host_valid():return self._respond(403,{'ok':False})
            self._respond(200,{'ok':True})

        def do_GET(self):
            if self.path!='/health' or not self._authorized():return self._respond(403,{'ok':False,'error':'Pair browser extension'})
            self._respond(200,{'ok':True,'application':'Maher Download Manager'})

        def do_POST(self):
            if self.path!='/add' or not self._authorized():return self._respond(403,{'ok':False,'error':'Pair browser extension'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=8192:raise ValueError('Invalid payload size')
                content=json.loads(self.rfile.read(size))
                url=content.get('url','')
                kind=content.get('kind','auto')
                if not isinstance(url,str) or not isinstance(kind,str):raise ValueError('Invalid request')
                job=manager.add(url,kind=kind)
                self._respond(200,{'ok':True,'id':job.id,'filename':job.filename})
            except (ValueError,TypeError,KeyError) as e:
                self._respond(400,{'ok':False,'error':str(e)})

        def log_message(self,*args):pass

    try:server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    except OSError:return None
    Thread(target=server.serve_forever,daemon=True,name='browser-bridge').start()
    return server
