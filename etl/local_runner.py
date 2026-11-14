"""不依赖 Airflow 的本地调度器：按 DAG 顺序调用同一批任务。"""
import sys, argparse
from .pipeline import run

def main():
    p = argparse.ArgumentParser(description='Control Tower 本地 ETL（示例数据）')
    p.add_argument('--keep-ods', action='store_true', help='不重建 ODS，只重算 DWD/ADS')
    args = p.parse_args()
    run(rebuild_ods=not args.keep_ods)

if __name__ == '__main__':
    main()
