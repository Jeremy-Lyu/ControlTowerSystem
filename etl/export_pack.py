"""导出 Power BI 可用数据包：每表一张 CSV + 一个 xlsx（主要维表与汇总）。"""
import os, csv, sqlite3
from .common import ROOT, connect, DB_PATH

OUT = os.path.join(ROOT, 'data_pack')
# 控制 xlsx 体积：只放维度、月度汇总、指标、注册表
XLSX_TABLES = [
    'dim_date','dim_plant','dim_shop','dim_shift','dim_supplier','dim_part','dim_defect','dim_equipment',
    'dim_jph_tier','dim_shift_pattern','dim_account','dim_buffer','dim_metric',
    'dws_group_month','dws_plant_month','dws_shop_month','dws_cost_account_month','dws_ga_daily',
    'ads_kpi_value','ads_action','dwd_dq_result','dwd_vcs_scenario',
]

def export(db=None):
    os.makedirs(OUT, exist_ok=True)
    con = connect(db or DB_PATH)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite%' ORDER BY 1")]
    for t in tables:
        path = os.path.join(OUT, t + '.csv')
        cur = con.execute(f'SELECT * FROM {t}')
        cols = [d[0] for d in cur.description]
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f); w.writerow(cols)
            for row in cur: w.writerow(list(row))
        print('  csv', t)
    # xlsx
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        readme = wb.create_sheet('README', 0)
        readme['A1'] = 'Manufacturing Control Tower 数据包（全部为示例数据）'
        readme['A2'] = 'X集团 / A·B·C 工厂；与看板、演示系统同一套数字。发出前请替换为真实数据。'
        readme['A3'] = '完整表见同目录 CSV。本工作簿仅含维度、月度汇总与指标，便于 Power BI 直接导入。'
        for t in XLSX_TABLES:
            if t not in tables: continue
            ws = wb.create_sheet(t[:31])
            cur = con.execute(f'SELECT * FROM {t}')
            cols = [d[0] for d in cur.description]
            ws.append(cols)
            n = 0
            for row in cur:
                ws.append(list(row)); n += 1
                if n >= 20000: break
        xls = os.path.join(OUT, 'Control_Tower_DataPack.xlsx')
        wb.save(xls)
        print('  xlsx', xls)
    except ImportError:
        print('openpyxl 未安装，跳过 xlsx')
    # data dictionary snippet
    with open(os.path.join(OUT, 'README.txt'), 'w', encoding='utf-8') as f:
        f.write('示例数据包 · 与 Control Tower 演示系统同一 SQLite 库导出。详见 docs/。\n')
        f.write('表清单：\n' + '\n'.join(tables))
    con.close()
    return OUT

if __name__ == '__main__':
    export()
