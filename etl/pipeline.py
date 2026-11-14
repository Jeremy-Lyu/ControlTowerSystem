"""本地 ETL 编排：ODS 生成 → DWD/DWS/ADS → 指标 YAML → 数据包。对应生产环境的 Airflow DAG。"""
from __future__ import annotations
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etl.common import connect, DB_PATH, load_story, set_workday_override, STORY_MONTH, CONFIG
from etl.targets import story_workdays, build_targets
from etl.generate_sources import generate
from etl.transform import transform
from etl import metrics as M

def run(rebuild_ods=True, verbose=True):
    t0 = time.time()
    S = load_story()
    set_workday_override(STORY_MONTH, story_workdays(S))
    os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
    con = connect()
    if rebuild_ods:
        if verbose: print('[1/4] 生成 ODS 源数据（示例，确定性）…')
        generate(con, verbose=verbose)
    else:
        if verbose: print('[1/4] 跳过 ODS 生成，使用现有库')
    if verbose: print('[2/4] ODS → DWD → DWS → ADS …')
    transform(con, verbose=verbose)
    if verbose: print('[3/4] 导出指标注册表 YAML …')
    M.dump_yaml(os.path.join(CONFIG, 'metrics.yaml'))
    if verbose: print('[4/4] 完成。库文件', DB_PATH, '用时', round(time.time()-t0, 1), 's')
    con.close()
    return DB_PATH

if __name__ == '__main__':
    rebuild = '--keep-ods' not in sys.argv
    run(rebuild_ods=rebuild)
