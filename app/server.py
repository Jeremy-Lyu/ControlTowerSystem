"""Control Tower 演示系统 Web 服务（仅用 Python 标准库：http.server + sqlite3）。
生产形态对应：Power BI 报表 + 华为云数仓 ADS 层；本演示用轻量服务模拟“统一指标层 + RLS + 行动闭环”。
"""
import json, os, re, sys, traceback, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etl.common import connect, DB_PATH
from app import api as A

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
MIME = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
        '.png': 'image/png', '.svg': 'image/svg+xml', '.json': 'application/json; charset=utf-8', '.ico': 'image/x-icon'}
_lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    server_version = 'ControlTowerDemo/1.0'
    def log_message(self, fmt, *args):
        if os.environ.get('CT_QUIET'): return
        sys.stderr.write('[ct] ' + fmt % args + '\n')

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Data-Label', 'EXAMPLE-DATA')
        self.end_headers()
        self.wfile.write(body)

    def _role(self):
        return self.headers.get('X-CT-Role') or 'group'

    def do_GET(self):  self._dispatch('GET')
    def do_POST(self): self._dispatch('POST')

    def _dispatch(self, method):
        u = urlparse(self.path)
        path = u.path
        q = {k: v[-1] for k, v in parse_qs(u.query).items()}
        try:
            if method == 'GET' and (path == '/' or path == '/index.html'):
                return self._file('index.html')
            if method == 'GET' and path.startswith('/static/'):
                return self._file(path[len('/static/'):])
            if path.startswith('/api/'):
                body = {}
                if method == 'POST':
                    n = int(self.headers.get('Content-Length') or 0)
                    body = json.loads(self.rfile.read(n) or b'{}') if n else {}
                con = connect()
                try:
                    with _lock if method == 'POST' else _nolock:
                        code, res = A.route(con, method, path, q, body, self._role())
                finally:
                    con.close()
                return self._send(code, res)
            return self._send(404, {'error': 'not found'})
        except A.Forbidden as e:
            return self._send(403, {'error': str(e)})
        except A.BadRequest as e:
            return self._send(400, {'error': str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {'error': '服务器错误：%s' % e})

    def _file(self, rel):
        p = os.path.normpath(os.path.join(STATIC, rel))
        if not p.startswith(STATIC) or not os.path.isfile(p):
            return self._send(404, {'error': 'not found'})
        ext = os.path.splitext(p)[1]
        with open(p, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', MIME.get(ext, 'application/octet-stream'))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'max-age=300' if 'vendor' in rel else 'no-cache')
        self.end_headers()
        self.wfile.write(data)

class _NoLock:
    def __enter__(self): return self
    def __exit__(self, *a): return False
_nolock = _NoLock()

def make_server(host='127.0.0.1', port=8050):
    return ThreadingHTTPServer((host, port), Handler)

def serve(host='127.0.0.1', port=8050):
    httpd = make_server(host, port)
    print(f'Control Tower 演示系统已启动： http://{host}:{port}   （示例数据 · Ctrl+C 退出）', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
