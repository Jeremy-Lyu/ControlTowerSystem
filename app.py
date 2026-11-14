#!/usr/bin/env python3
"""启动 Control Tower 演示系统：python3 app.py [--port 8050]"""
import argparse, os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from etl.common import DB_PATH

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=int(os.environ.get('CT_PORT', 8050)))
    args = p.parse_args()
    if not os.path.exists(DB_PATH):
        print('未找到数据库，正在构建示例数据…')
        from etl.pipeline import run
        run()
    from app.server import serve
    serve(args.host, args.port)

if __name__ == '__main__':
    main()
