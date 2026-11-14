"""把看板示例数据(data.py)同步成系统的对账目标 config/story_targets.json。
用法: python3 tools/sync_story.py [path/to/data.py]
data.py 是看板/PPT 的唯一示例数据源; 本系统的数据生成器只读取 JSON, 保证数字一致。
"""
import json, sys, os, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = sys.argv[1] if len(sys.argv) > 1 else '/workspace/ControlTower/_src/data.py'
ns = {'__name__': 'story'}
exec(compile(open(src, encoding='utf-8').read(), src, 'exec'), ns)
def conv(v):
    try:
        import numpy as np
        if isinstance(v, np.generic): return v.item()
        if isinstance(v, np.ndarray): return v.tolist()
    except ImportError: pass
    if isinstance(v, dict): return {str(k): conv(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [conv(x) for x in v]
    return v
out = {}
for k, v in ns.items():
    if k.startswith('_') and k not in ('_tot_ot',): continue
    if isinstance(v, (types.ModuleType, types.FunctionType, type)): continue
    v = conv(v)
    try: json.dumps(v); out[k] = v
    except TypeError: pass
out['_source'] = os.path.basename(src)
dst = os.path.join(ROOT, 'config', 'story_targets.json')
json.dump(out, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', dst, len(out), 'keys')

# ---- 指标清单（KPI_List.xlsx → config/kpi_list.json；系统运行时不依赖 openpyxl）----
try:
    import openpyxl
    xl = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.dirname(src)), 'Control_Tower_KPI_List.xlsx')
    wb = openpyxl.load_workbook(xl, read_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == '指标名')
    keys = ['name', 'level', 'process', 'definition', 'formula', 'source', 'refresh', 'owner_role', 'it_role', 'dq_rule', 'target_text']
    items = [dict(zip(keys, [str(x).strip() if x is not None else '' for x in r[:11]])) for r in rows[hi + 1:] if r and r[0]]
    json.dump(items, open(os.path.join(ROOT, 'config', 'kpi_list.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote kpi_list.json', len(items), 'items')
except ImportError:
    print('openpyxl 未安装：跳过 KPI 清单同步（沿用已有 config/kpi_list.json）')
