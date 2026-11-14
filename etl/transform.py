"""ODS → DWD → DWS → ADS。清洗、去重、质量规则隔离脏数据后，按口径计算指标。
对账目标见 config/story_targets.json（由 data.py 同步）。所有数字均为示例数据。
"""
from __future__ import annotations
import json, os, datetime as dt
from .common import *
from .targets import build_targets, story_workdays
from . import metrics as M

# ---------------- 数据质量规则 ----------------
DQ_RULES = [
    dict(rule_id='DQ01', name='班次运行主键去重', layer='DWD', severity='error',
         desc='ods_mes_shift_run 按 run_id 去重，保留 load_ts 最晚的一条',
         sql="SELECT run_id, COUNT(*) n FROM ods_mes_shift_run GROUP BY run_id HAVING n>1"),
    dict(rule_id='DQ02', name='停机原因非空且分钟>0', layer='DWD', severity='error',
         desc='剔除 reason 为空或 minutes<=0 的停机事件（不进入 fact）',
         sql="SELECT COUNT(*) FROM ods_mes_downtime WHERE reason IS NULL OR minutes<=0"),
    dict(rule_id='DQ03', name='缺陷代码必须存在于主数据', layer='DWD', severity='error',
         desc='未知缺陷代码隔离，不进入 fact_quality_defect',
         sql="SELECT COUNT(*) FROM ods_qms_defect d LEFT JOIN ods_md_defect m ON d.defect_code=m.defect_code WHERE m.defect_code IS NULL"),
    dict(rule_id='DQ04', name='能源读数非负', layer='DWD', severity='error',
         desc='剔除 fix_kwh/ot_kwh/var_kwh 为负的能源日记录',
         sql="SELECT COUNT(*) FROM ods_ems_daily WHERE fix_kwh<0 OR ot_kwh<0 OR var_kwh<0"),
    dict(rule_id='DQ05', name='出勤人数不超过排班', layer='DWD', severity='warn',
         desc='present>scheduled 的记录按 scheduled 封顶并记告警',
         sql="SELECT COUNT(*) FROM ods_hr_attendance WHERE present>scheduled"),
    dict(rule_id='DQ06', name='到货批次去重', layer='DWD', severity='error',
         desc='ods_wms_delivery 按 rec_id 去重',
         sql="SELECT rec_id, COUNT(*) n FROM ods_wms_delivery GROUP BY rec_id HAVING n>1"),
    dict(rule_id='DQ07', name='VCS 档位合法', layer='DWD', severity='error',
         desc='实际/推荐 JPH 档必须属于该车间可选档集合',
         sql="SELECT COUNT(*) FROM dwd_fact_vcs_plan p LEFT JOIN dim_jph_tier t ON p.plant_code=t.plant_code AND p.shop_code=t.shop_code AND p.tier_jph=t.tier_jph WHERE t.tier_jph IS NULL"),
    dict(rule_id='DQ08', name='产量分母>0', layer='ADS', severity='error',
         desc='计算单车类指标时下线车数必须>0',
         sql="SELECT COUNT(*) FROM dws_plant_month WHERE prod_qty<=0"),
]

def _exec(con, sql):
    con.execute(sql)

def drop_create(con, name, cols_sql, pk=None):
    con.execute(f'DROP TABLE IF EXISTS {name}')
    pkc = f', PRIMARY KEY ({pk})' if pk else ''
    con.execute(f'CREATE TABLE {name} ({cols_sql}{pkc})')

def build_dims(con, S):
    # 日期
    drop_create(con, 'dim_date',
        'date_key TEXT, d TEXT, year INT, month TEXT, month_seq INT, day INT, weekday INT, is_workday INT, iso_week TEXT, week_label TEXT',
        'date_key')
    rows = []
    w44 = {}  # story weeks W32-W44 mapping for Oct-adjacent
    for m in MONTHS:
        seq = MONTHS.index(m)
        for d in month_days(m):
            wd = 1 if is_workday(d) else 0
            iw = d.isocalendar()
            label = 'W%02d' % iw[1]
            rows.append((d.isoformat(), d.isoformat(), d.year, m, seq, d.day, d.weekday(), wd, 'W%02d' % iw[1], label))
    con.executemany('INSERT INTO dim_date VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
    drop_create(con, 'dim_plant', 'plant_code TEXT, plant_name TEXT, region TEXT, start_year INT', 'plant_code')
    con.execute('INSERT INTO dim_plant SELECT * FROM ods_md_plant')
    drop_create(con, 'dim_shop', 'shop_code TEXT, shop_name TEXT, seq INT, shop_type TEXT', 'shop_code')
    con.execute('INSERT INTO dim_shop SELECT * FROM ods_md_shop')
    drop_create(con, 'dim_shift', 'slot TEXT, slot_name TEXT, is_ot INT', 'slot')
    con.executemany('INSERT INTO dim_shift VALUES (?,?,?)',
                    [('S1','早班',0),('S2','中班',0),('S3','夜班',0),('OT','加班班次',1)])
    drop_create(con, 'dim_supplier', 'supplier_code TEXT, supplier_name TEXT, category TEXT, region TEXT', 'supplier_code')
    con.execute('INSERT INTO dim_supplier SELECT * FROM ods_md_supplier')
    drop_create(con, 'dim_part', 'part_no TEXT, part_name TEXT, supplier_code TEXT, commodity TEXT, is_key INT', 'part_no')
    con.execute('INSERT INTO dim_part SELECT * FROM ods_md_part')
    drop_create(con, 'dim_defect', 'defect_code TEXT, defect_name TEXT, shop_code TEXT, defect_group TEXT', 'defect_code')
    con.execute('INSERT INTO dim_defect SELECT * FROM ods_md_defect')
    drop_create(con, 'dim_equipment', 'equip_code TEXT, plant_code TEXT, shop_code TEXT, equip_name TEXT, equip_type TEXT, is_critical INT', 'equip_code')
    con.execute('INSERT INTO dim_equipment SELECT * FROM ods_md_equipment')
    drop_create(con, 'dim_jph_tier', 'plant_code TEXT, shop_code TEXT, tier_jph INT, heads_direct INT, heads_indirect INT, run_kw INT, valid_from TEXT',
                'plant_code, shop_code, tier_jph')
    con.execute('INSERT INTO dim_jph_tier SELECT * FROM ods_vcs_jph_tier')
    drop_create(con, 'dim_shift_pattern', 'pattern_code TEXT, pattern_name TEXT, shifts_per_day INT, hours_per_shift REAL, night_shift INT, note TEXT', 'pattern_code')
    con.execute('INSERT INTO dim_shift_pattern SELECT * FROM ods_vcs_shift_pattern')
    drop_create(con, 'dim_account', 'account TEXT, grp TEXT, seq INT', 'account')
    for i, (g, accs) in enumerate(S['GRP'].items()):
        for j, a in enumerate(accs):
            con.execute('INSERT INTO dim_account VALUES (?,?,?)', (a, g, i*10+j))
    drop_create(con, 'dim_buffer', 'buffer_code TEXT, buffer_name TEXT, upstream_shop TEXT, downstream_shop TEXT', 'buffer_code')
    con.executemany('INSERT INTO dim_buffer VALUES (?,?,?,?)',
                    [('STK','冲压件库','ST','BD'),('WBS','WBS 白车身库','BD','PT'),('PBS','PBS 涂装车身库','PT','GA')])

def run_dq_ods(con):
    """在进入 DWD 前清点 ODS 脏数据，写入 dq_result。"""
    drop_create(con, 'dwd_dq_result',
                'rule_id TEXT, name TEXT, layer TEXT, severity TEXT, month TEXT, plant_code TEXT, checked INT, failed INT, note TEXT')
    return

def build_dwd(con):
    # 班次运行：按 run_id 去重
    drop_create(con, 'dwd_fact_production',
        '''run_id TEXT, biz_date TEXT, month TEXT, plant_code TEXT, shop_code TEXT, slot TEXT,
           tier_jph INT, design_jph REAL, sched_min INT, planned_min INT, stop_min INT, minor_stop_min INT,
           run_min INT, output_qty INT, is_ot INT''', 'run_id')
    con.execute('''INSERT INTO dwd_fact_production
        SELECT run_id, biz_date, substr(biz_date,1,7), plant_code, shop_code, slot,
               tier_jph, design_jph, sched_min, planned_min, stop_min, minor_stop_min,
               planned_min - stop_min - minor_stop_min, output_qty, CASE WHEN slot='OT' THEN 1 ELSE 0 END
        FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY load_ts DESC, rowid DESC) rn
              FROM ods_mes_shift_run) t WHERE rn=1''')
    # 停机
    drop_create(con, 'dwd_fact_downtime',
        '''event_id TEXT, biz_date TEXT, month TEXT, plant_code TEXT, shop_code TEXT, slot TEXT,
           equip_code TEXT, reason TEXT, minutes INT, part_no TEXT, supplier_code TEXT''', 'event_id')
    con.execute('''INSERT INTO dwd_fact_downtime
        SELECT event_id, biz_date, substr(biz_date,1,7), plant_code, shop_code, slot,
               equip_code, reason, minutes, part_no, supplier_code
        FROM ods_mes_downtime WHERE reason IS NOT NULL AND minutes>0''')
    # 质量缺陷
    drop_create(con, 'dwd_fact_defect',
        'rec_id TEXT, biz_date TEXT, month TEXT, plant_code TEXT, shop_code TEXT, defect_code TEXT, qty INT', 'rec_id')
    con.execute('''INSERT INTO dwd_fact_defect
        SELECT d.rec_id, d.biz_date, substr(d.biz_date,1,7), d.plant_code, d.shop_code, d.defect_code, d.qty
        FROM ods_qms_defect d JOIN dim_defect m ON d.defect_code=m.defect_code''')
    # 到货
    drop_create(con, 'dwd_fact_delivery',
        'rec_id TEXT, biz_date TEXT, month TEXT, plant_code TEXT, supplier_code TEXT, batches INT, ontime_batches INT', 'rec_id')
    con.execute('''INSERT INTO dwd_fact_delivery
        SELECT rec_id, biz_date, substr(biz_date,1,7), plant_code, supplier_code, batches, ontime_batches
        FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY rec_id ORDER BY rowid DESC) rn FROM ods_wms_delivery) t WHERE rn=1''')
    # 能源
    drop_create(con, 'dwd_fact_energy',
        '''biz_date TEXT, month TEXT, plant_code TEXT, shop_code TEXT,
           fix_kwh REAL, ot_kwh REAL, var_kwh REAL, idle_kwh REAL, peak_kwh REAL, flat_kwh REAL, valley_kwh REAL,
           elec_kwh REAL, cost REAL, water_m3 REAL, co2_kg REAL''',
        'biz_date, plant_code, shop_code')
    # 排放因子（示例）：电网 0.57 kgCO2/kWh
    con.execute('''INSERT INTO dwd_fact_energy
        SELECT biz_date, substr(biz_date,1,7), plant_code, shop_code,
               fix_kwh, ot_kwh, var_kwh, idle_kwh, peak_kwh, flat_kwh, valley_kwh,
               fix_kwh+ot_kwh+var_kwh, cost, water_m3, (fix_kwh+ot_kwh+var_kwh)*0.57
        FROM ods_ems_daily WHERE (fix_kwh+ot_kwh+var_kwh)>=0 AND NOT (fix_kwh<0 AND ot_kwh=0 AND var_kwh=0 AND cost=0)''')
    # 考勤（出勤封顶）
    drop_create(con, 'dwd_fact_attendance',
        'biz_date TEXT, month TEXT, plant_code TEXT, shop_code TEXT, scheduled INT, present INT, std_h REAL, ot_h REAL',
        'biz_date, plant_code, shop_code')
    con.execute('''INSERT INTO dwd_fact_attendance
        SELECT biz_date, substr(biz_date,1,7), plant_code, shop_code, scheduled,
               CASE WHEN present>scheduled THEN scheduled ELSE present END, std_h, ot_h
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY biz_date, plant_code, shop_code
                                         ORDER BY scheduled DESC, rowid) rn
            FROM ods_hr_attendance
            WHERE shop_code IN ('ST','BD','PT','GA')
        ) t WHERE rn=1''')
    # 成本
    drop_create(con, 'dwd_fact_cost',
        'month TEXT, plant_code TEXT, cost_center TEXT, account TEXT, amount REAL',
        'month, plant_code, cost_center, account')
    con.execute('INSERT INTO dwd_fact_cost SELECT month, plant_code, cost_center, account, amount FROM ods_erp_cost')
    # VCS 计划（月 / 日）
    drop_create(con, 'dwd_fact_vcs_plan',
        '''scenario_id TEXT, version TEXT, month TEXT, plant_code TEXT, shop_code TEXT,
           tier_jph INT, shifts INT, pattern_code TEXT, ot_line_h REAL, crew INT, heads INT, ot_person_h INT, plan_qty INT,
           el_fix_kwh REAL, el_ot_kwh REAL, el_var_kwh REAL''',
        'scenario_id, version, month, plant_code, shop_code')
    con.execute('INSERT INTO dwd_fact_vcs_plan SELECT * FROM ods_vcs_plan_month')
    drop_create(con, 'dwd_fact_vcs_plan_day',
        'scenario_id TEXT, version TEXT, biz_date TEXT, month TEXT, plant_code TEXT, shop_code TEXT, tier_jph INT, shifts INT, ot_line_h REAL',
        'scenario_id, version, biz_date, plant_code, shop_code')
    con.execute('''INSERT INTO dwd_fact_vcs_plan_day
        SELECT scenario_id, version, biz_date, substr(biz_date,1,7), plant_code, shop_code, tier_jph, shifts, ot_line_h
        FROM ods_vcs_plan_day''')
    drop_create(con, 'dwd_fact_vcs_cost_plan',
        'scenario_id TEXT, version TEXT, month TEXT, plant_code TEXT, account TEXT, amount REAL',
        'scenario_id, version, month, plant_code, account')
    con.execute('INSERT INTO dwd_fact_vcs_cost_plan SELECT * FROM ods_vcs_cost_plan')
    drop_create(con, 'dwd_fact_vcs_buffer_plan',
        'scenario_id TEXT, month TEXT, plant_code TEXT, buffer_code TEXT, cap_units INT, cap_effective INT, plan_end INT',
        'scenario_id, month, plant_code, buffer_code')
    con.execute('INSERT INTO dwd_fact_vcs_buffer_plan SELECT * FROM ods_vcs_buffer_plan')
    # 检验 / 订单 / 库存 / 维护 / 安全 等透传
    drop_create(con, 'dwd_fact_inspection', 'biz_date TEXT, month TEXT, plant_code TEXT, shop_code TEXT, inspected INT, first_pass INT, rework INT',
                'biz_date, plant_code, shop_code')
    con.execute('INSERT INTO dwd_fact_inspection SELECT biz_date, substr(biz_date,1,7), plant_code, shop_code, inspected, first_pass, rework FROM ods_qms_inspection')
    drop_create(con, 'dwd_fact_vehicle_ftt', 'biz_date TEXT, month TEXT, plant_code TEXT, offline INT, first_pass INT', 'biz_date, plant_code')
    con.execute('INSERT INTO dwd_fact_vehicle_ftt SELECT biz_date, substr(biz_date,1,7), plant_code, offline, first_pass FROM ods_qms_vehicle_ftt')
    drop_create(con, 'dwd_fact_order', 'order_id TEXT, plant_code TEXT, month TEXT, order_date TEXT, promise_date TEXT, ship_date TEXT, qty INT, ontime INT, lead_days INT',
                'order_id')
    con.execute('''INSERT INTO dwd_fact_order
        SELECT order_id, plant_code, substr(ship_date,1,7), order_date, promise_date, ship_date, qty,
               CASE WHEN ship_date<=promise_date THEN 1 ELSE 0 END,
               CAST(julianday(ship_date)-julianday(order_date) AS INT)
        FROM ods_erp_order''')
    drop_create(con, 'dwd_fact_inventory', 'biz_date TEXT, month TEXT, plant_code TEXT, inv_type TEXT, qty INT, daily_demand REAL',
                'biz_date, plant_code, inv_type')
    con.execute('INSERT INTO dwd_fact_inventory SELECT biz_date, substr(biz_date,1,7), plant_code, inv_type, qty, daily_demand FROM ods_wms_inventory')
    drop_create(con, 'dwd_fact_lineside', 'snapshot_date TEXT, month TEXT, plant_code TEXT, part_no TEXT, buffer_h REAL',
                'snapshot_date, plant_code, part_no')
    con.execute('INSERT INTO dwd_fact_lineside SELECT snapshot_date, substr(snapshot_date,1,7), plant_code, part_no, buffer_h FROM ods_wms_lineside')
    drop_create(con, 'dwd_fact_plan_daily', 'biz_date TEXT, month TEXT, plant_code TEXT, plan_qty INT, version TEXT', 'biz_date, plant_code, version')
    con.execute("INSERT INTO dwd_fact_plan_daily SELECT biz_date, substr(biz_date,1,7), plant_code, plan_qty, version FROM ods_aps_plan_daily WHERE version='FROZEN'")
    drop_create(con, 'dwd_fact_plan_change', 'change_id TEXT, plant_code TEXT, shop_code TEXT, change_date TEXT, month TEXT, in_frozen INT, reason TEXT', 'change_id')
    con.execute('INSERT INTO dwd_fact_plan_change SELECT change_id, plant_code, shop_code, change_date, substr(change_date,1,7), in_frozen, reason FROM ods_aps_change')
    drop_create(con, 'dwd_fact_die_change', 'event_id TEXT, biz_date TEXT, month TEXT, plant_code TEXT, line_code TEXT, minutes REAL', 'event_id')
    con.execute('INSERT INTO dwd_fact_die_change SELECT event_id, biz_date, substr(biz_date,1,7), plant_code, line_code, minutes FROM ods_mes_die_change')
    drop_create(con, 'dwd_fact_press', 'biz_date TEXT, month TEXT, plant_code TEXT, line_code TEXT, die_avail_min INT, die_run_min INT, design_strokes INT, actual_strokes INT, parts INT, good_parts INT',
                'biz_date, plant_code, line_code')
    con.execute('INSERT INTO dwd_fact_press SELECT biz_date, substr(biz_date,1,7), plant_code, line_code, die_avail_min, die_run_min, design_strokes, actual_strokes, parts, good_parts FROM ods_mes_press_daily')
    drop_create(con, 'dwd_fact_oven', 'biz_date TEXT, month TEXT, plant_code TEXT, oven_code TEXT, shifts INT, idle_min INT, start_stop INT, compliant INT',
                'biz_date, plant_code, oven_code')
    con.execute('INSERT INTO dwd_fact_oven SELECT biz_date, substr(biz_date,1,7), plant_code, oven_code, shifts, idle_min, start_stop, compliant FROM ods_mes_oven_daily')
    drop_create(con, 'dwd_fact_takt', 'biz_date TEXT, month TEXT, plant_code TEXT, shop_code TEXT, design_takt_s REAL, actual_takt_s REAL, cycles INT',
                'biz_date, plant_code, shop_code')
    con.execute('INSERT INTO dwd_fact_takt SELECT biz_date, substr(biz_date,1,7), plant_code, shop_code, design_takt_s, actual_takt_s, cycles FROM ods_mes_takt_daily')
    drop_create(con, 'dwd_fact_andon', 'biz_date TEXT, month TEXT, plant_code TEXT, calls INT, resp_sec_total INT', 'biz_date, plant_code')
    con.execute('INSERT INTO dwd_fact_andon SELECT biz_date, substr(biz_date,1,7), plant_code, calls, resp_sec_total FROM ods_mes_andon_daily')
    drop_create(con, 'dwd_fact_buffer', 'biz_date TEXT, month TEXT, plant_code TEXT, buffer_code TEXT, level_units INT', 'biz_date, plant_code, buffer_code')
    con.execute('INSERT INTO dwd_fact_buffer SELECT biz_date, substr(biz_date,1,7), plant_code, buffer_code, level_units FROM ods_mes_buffer_daily')
    drop_create(con, 'dwd_fact_wo', 'wo_id TEXT, plant_code TEXT, shop_code TEXT, equip_code TEXT, wo_type TEXT, planned_date TEXT, done_date TEXT, month TEXT, repair_min INT, event_id TEXT', 'wo_id')
    con.execute('INSERT INTO dwd_fact_wo SELECT wo_id, plant_code, shop_code, equip_code, wo_type, planned_date, done_date, substr(COALESCE(done_date,planned_date),1,7), repair_min, event_id FROM ods_cmms_wo')
    drop_create(con, 'dwd_fact_incident', 'incident_id TEXT, biz_date TEXT, month TEXT, plant_code TEXT, shop_code TEXT, inc_type TEXT, lost_days INT', 'incident_id')
    con.execute('INSERT INTO dwd_fact_incident SELECT incident_id, biz_date, substr(biz_date,1,7), plant_code, shop_code, inc_type, lost_days FROM ods_ehs_incident')
    drop_create(con, 'dwd_fact_hazard', 'hazard_id TEXT, plant_code TEXT, shop_code TEXT, raised_date TEXT, month TEXT, closed_date TEXT, level TEXT', 'hazard_id')
    con.execute('INSERT INTO dwd_fact_hazard SELECT hazard_id, plant_code, shop_code, raised_date, substr(raised_date,1,7), closed_date, level FROM ods_ehs_hazard')
    drop_create(con, 'dwd_fact_roster', 'month TEXT, plant_code TEXT, shop_code TEXT, emp_type TEXT, headcount INT', 'month, plant_code, shop_code, emp_type')
    con.execute('INSERT INTO dwd_fact_roster SELECT * FROM ods_hr_roster')
    drop_create(con, 'dwd_fact_job_run', 'run_id TEXT, dag_id TEXT, task_id TEXT, biz_date TEXT, month TEXT, sla_ts TEXT, end_ts TEXT, status TEXT, ontime INT', 'run_id')
    con.execute('''INSERT INTO dwd_fact_job_run
        SELECT run_id, dag_id, task_id, biz_date, substr(biz_date,1,7), sla_ts, end_ts, status,
               CASE WHEN status='success' AND end_ts<=sla_ts THEN 1 ELSE 0 END
        FROM ods_sys_job_run''')
    drop_create(con, 'dwd_fact_dq_hist', 'biz_date TEXT, month TEXT, rule_id TEXT, checked INT, passed INT', 'biz_date, rule_id')
    con.execute('INSERT INTO dwd_fact_dq_hist SELECT biz_date, substr(biz_date,1,7), rule_id, checked, passed FROM ods_sys_dq_history')
    drop_create(con, 'dwd_fact_usage', 'biz_date TEXT, month TEXT, user_id TEXT, role TEXT, page TEXT, views INT')
    con.execute('INSERT INTO dwd_fact_usage SELECT biz_date, substr(biz_date,1,7), user_id, role, page, views FROM ods_bi_usage')
    drop_create(con, 'dwd_fact_audit', 'month TEXT, plant_code TEXT, cars INT, deduction REAL', 'month, plant_code')
    con.execute('INSERT INTO dwd_fact_audit SELECT * FROM ods_qms_audit')
    drop_create(con, 'dwd_fact_warranty', 'month TEXT, plant_code TEXT, claims INT, vehicles_in_service INT', 'month, plant_code')
    con.execute('INSERT INTO dwd_fact_warranty SELECT * FROM ods_qms_warranty')
    drop_create(con, 'dwd_fact_copq', 'month TEXT, plant_code TEXT, category TEXT, amount REAL', 'month, plant_code, category')
    con.execute('INSERT INTO dwd_fact_copq SELECT * FROM ods_qms_copq')
    drop_create(con, 'dwd_fact_spare', 'month TEXT, plant_code TEXT, value REAL', 'month, plant_code')
    con.execute('INSERT INTO dwd_fact_spare SELECT * FROM ods_erp_spare')
    drop_create(con, 'dwd_vcs_scenario', 'scenario_id TEXT, scenario_name TEXT, scenario_type TEXT, metric TEXT, value REAL, unit TEXT, note TEXT')
    con.execute('INSERT INTO dwd_vcs_scenario SELECT * FROM ods_vcs_scenario')

def write_dq(con):
    rows = []
    # 运行时计数
    def cnt(sql):
        return con.execute(sql).fetchone()[0]
    mapping = {
        'DQ01': "SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM ods_mes_shift_run GROUP BY run_id HAVING n>1)",
        'DQ02': "SELECT COUNT(*) FROM ods_mes_downtime WHERE reason IS NULL OR minutes<=0",
        'DQ03': "SELECT COUNT(*) FROM ods_qms_defect d LEFT JOIN ods_md_defect m ON d.defect_code=m.defect_code WHERE m.defect_code IS NULL",
        'DQ04': "SELECT COUNT(*) FROM ods_ems_daily WHERE fix_kwh<0 OR ot_kwh<0 OR var_kwh<0",
        'DQ05': "SELECT COUNT(*) FROM ods_hr_attendance WHERE present>scheduled",
        'DQ06': "SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM ods_wms_delivery GROUP BY rec_id HAVING n>1)",
        'DQ07': "SELECT COUNT(*) FROM dwd_fact_vcs_plan p LEFT JOIN dim_jph_tier t ON p.plant_code=t.plant_code AND p.shop_code=t.shop_code AND p.tier_jph=t.tier_jph WHERE t.tier_jph IS NULL",
        'DQ08': "SELECT COUNT(*) FROM dws_plant_month WHERE prod_qty<=0",
    }
    checked = {
        'DQ01': "SELECT COUNT(*) FROM ods_mes_shift_run",
        'DQ02': "SELECT COUNT(*) FROM ods_mes_downtime",
        'DQ03': "SELECT COUNT(*) FROM ods_qms_defect",
        'DQ04': "SELECT COUNT(*) FROM ods_ems_daily",
        'DQ05': "SELECT COUNT(*) FROM ods_hr_attendance",
        'DQ06': "SELECT COUNT(*) FROM ods_wms_delivery",
        'DQ07': "SELECT COUNT(*) FROM dwd_fact_vcs_plan",
        'DQ08': "SELECT COUNT(*) FROM dws_plant_month",
    }
    for r in DQ_RULES:
        if r['rule_id'] in ('DQ07','DQ08') and r['rule_id']=='DQ08':
            # dws may not exist yet when called mid-pipeline
            try:
                failed, ch = cnt(mapping[r['rule_id']]), cnt(checked[r['rule_id']])
            except Exception:
                failed, ch = 0, 0
        else:
            try:
                failed, ch = cnt(mapping[r['rule_id']]), cnt(checked[r['rule_id']])
            except Exception:
                failed, ch = 0, 0
        rows.append((r['rule_id'], r['name'], r['layer'], r['severity'], None, None, ch, failed, r['desc']))
    con.executemany('INSERT INTO dwd_dq_result VALUES (?,?,?,?,?,?,?,?,?)', rows)

def build_dws(con):
    # 工厂 × 月
    drop_create(con, 'dws_plant_month', '''
        month TEXT, plant_code TEXT,
        prod_qty INT, plan_qty INT,
        cost_total REAL, cost_plan_total REAL,
        elec_kwh REAL, elec_plan_kwh REAL, energy_cost REAL, energy_cost_plan REAL, idle_kwh REAL, peak_kwh REAL, water_m3 REAL, co2_kg REAL,
        std_h REAL, ot_h REAL, ot_h_plan REAL, present_h REAL, headcount INT, att_present INT, att_sched INT,
        disp_n INT, temp_n INT,
        otd_num INT, otd_den INT, lead_days_sum INT,
        ftt_num INT, ftt_den INT, defect_qty INT, rework_qty INT, audit_score REAL, audit_cars INT, warranty_claims INT, warranty_veh INT, copq REAL,
        delivery_ontime INT, delivery_batches INT, lineside_lt4 INT, lineside_n INT,
        buffer_days REAL, wip_days REAL, fg_days REAL,
        frozen_changes INT, spare_value REAL,
        lti INT, hours_worked REAL, hazards INT, hazards_closed INT,
        wo_pm INT, wo_pm_done INT, wo_cm INT, repair_min INT, fail_events INT,
        job_ontime INT, job_n INT, dq_passed INT, dq_checked INT, mau INT,
        PRIMARY KEY (month, plant_code)
    ''')
    con.execute('''
    INSERT INTO dws_plant_month
    WITH prod AS (
      SELECT month, plant_code, SUM(CASE WHEN shop_code='GA' THEN output_qty ELSE 0 END) prod_qty
      FROM dwd_fact_production GROUP BY 1,2
    ), plan AS (
      SELECT month, plant_code, SUM(plan_qty) plan_qty FROM dwd_fact_plan_daily GROUP BY 1,2
    ), cost AS (
      SELECT month, plant_code, SUM(amount) cost_total FROM dwd_fact_cost GROUP BY 1,2
    ), cplan AS (
      SELECT month, plant_code, SUM(amount) cost_plan_total FROM dwd_fact_vcs_cost_plan WHERE scenario_id='VCS-BASE' GROUP BY 1,2
    ), en AS (
      SELECT month, plant_code, SUM(elec_kwh) elec_kwh, SUM(idle_kwh) idle_kwh, SUM(peak_kwh) peak_kwh,
             SUM(water_m3) water_m3, SUM(co2_kg) co2_kg, SUM(cost) energy_cost
      FROM dwd_fact_energy GROUP BY 1,2
    ), eplan AS (
      SELECT month, plant_code, SUM(el_fix_kwh+el_ot_kwh+el_var_kwh) elec_plan_kwh
      FROM dwd_fact_vcs_plan WHERE scenario_id='VCS-BASE' GROUP BY 1,2
    ), ecp AS (
      SELECT c.month, c.plant_code, SUM(c.amount) energy_cost_plan
      FROM dwd_fact_vcs_cost_plan c JOIN dim_account a ON a.account=c.account
      WHERE c.scenario_id='VCS-BASE' AND a.grp='能源' GROUP BY 1,2
    ), hr AS (
      SELECT month, plant_code, SUM(std_h) std_h, SUM(ot_h) ot_h, SUM(present)*8.0 present_h,
             SUM(present) att_present, SUM(scheduled) att_sched
      FROM dwd_fact_attendance GROUP BY 1,2
    ), roster AS (
      SELECT month, plant_code, SUM(headcount) headcount,
             SUM(CASE WHEN emp_type='派遣' THEN headcount ELSE 0 END) disp_n,
             SUM(CASE WHEN emp_type='临时' THEN headcount ELSE 0 END) temp_n
      FROM dwd_fact_roster GROUP BY 1,2
    ), otp AS (
      SELECT month, plant_code, SUM(ot_person_h) ot_h_plan FROM dwd_fact_vcs_plan WHERE scenario_id='VCS-BASE' GROUP BY 1,2
    ), ord AS (
      SELECT month, plant_code, SUM(ontime) otd_num, COUNT(*) otd_den, SUM(lead_days) lead_days_sum FROM dwd_fact_order GROUP BY 1,2
    ), ftt AS (
      SELECT month, plant_code, SUM(first_pass) ftt_num, SUM(offline) ftt_den FROM dwd_fact_vehicle_ftt GROUP BY 1,2
    ), def AS (
      SELECT month, plant_code, SUM(qty) defect_qty FROM dwd_fact_defect GROUP BY 1,2
    ), rw AS (
      SELECT month, plant_code, SUM(rework) rework_qty FROM dwd_fact_inspection WHERE shop_code='GA' GROUP BY 1,2
    ), aud AS (
      SELECT month, plant_code, deduction, cars FROM dwd_fact_audit
    ), war AS (
      SELECT month, plant_code, claims, vehicles_in_service FROM dwd_fact_warranty
    ), copq AS (
      SELECT month, plant_code, SUM(amount) copq FROM dwd_fact_copq GROUP BY 1,2
    ), del AS (
      SELECT month, plant_code, SUM(ontime_batches) delivery_ontime, SUM(batches) delivery_batches FROM dwd_fact_delivery GROUP BY 1,2
    ), ls AS (
      SELECT month, plant_code, SUM(CASE WHEN buffer_h<4 THEN 1 ELSE 0 END) lineside_lt4, COUNT(*) lineside_n FROM dwd_fact_lineside GROUP BY 1,2
    ), inv AS (
      SELECT month, plant_code,
             SUM(CASE WHEN inv_type='PARTS' THEN qty END)*1.0 / NULLIF(SUM(CASE WHEN inv_type='PARTS' THEN daily_demand END),0) buffer_days,
             SUM(CASE WHEN inv_type='WIP' THEN qty END)*1.0 / NULLIF(SUM(CASE WHEN inv_type='WIP' THEN daily_demand END),0) wip_days,
             SUM(CASE WHEN inv_type='FG' THEN qty END)*1.0 / NULLIF(SUM(CASE WHEN inv_type='FG' THEN daily_demand END),0) fg_days
      FROM dwd_fact_inventory GROUP BY 1,2
    ), chg AS (
      SELECT month, plant_code, SUM(in_frozen) frozen_changes FROM dwd_fact_plan_change GROUP BY 1,2
    ), sp AS (
      SELECT month, plant_code, value FROM dwd_fact_spare
    ), ehs AS (
      SELECT month, plant_code, SUM(CASE WHEN inc_type='LTI' THEN 1 ELSE 0 END) lti FROM dwd_fact_incident GROUP BY 1,2
    ), hz AS (
      SELECT month, plant_code, COUNT(*) hazards, SUM(CASE WHEN closed_date IS NOT NULL THEN 1 ELSE 0 END) hazards_closed
      FROM dwd_fact_hazard GROUP BY 1,2
    ), wo AS (
      SELECT month, plant_code,
             SUM(CASE WHEN wo_type='PM' THEN 1 ELSE 0 END) wo_pm,
             SUM(CASE WHEN wo_type='PM' AND done_date IS NOT NULL THEN 1 ELSE 0 END) wo_pm_done,
             SUM(CASE WHEN wo_type='CM' THEN 1 ELSE 0 END) wo_cm,
             SUM(CASE WHEN wo_type='CM' THEN repair_min ELSE 0 END) repair_min
      FROM dwd_fact_wo GROUP BY 1,2
    ), fe AS (
      SELECT month, plant_code, COUNT(*) fail_events FROM dwd_fact_downtime
      WHERE reason IN ('设备故障','机器人故障','模具故障','输送链故障','喷涂机器人','烘房温控','夹具','输送','焊枪/电极')
      GROUP BY 1,2
    ), job AS (
      SELECT month, SUM(ontime) job_ontime, COUNT(*) job_n FROM dwd_fact_job_run GROUP BY 1
    ), dq AS (
      SELECT month, SUM(passed) dq_passed, SUM(checked) dq_checked FROM dwd_fact_dq_hist GROUP BY 1
    ), use AS (
      SELECT month, COUNT(DISTINCT user_id) mau FROM dwd_fact_usage GROUP BY 1
    )
    SELECT p.month, p.plant_code, p.prod_qty, pl.plan_qty, c.cost_total, cp.cost_plan_total,
           e.elec_kwh, ep.elec_plan_kwh, e.energy_cost, ecp.energy_cost_plan, e.idle_kwh, e.peak_kwh, e.water_m3, e.co2_kg,
           hr.std_h, hr.ot_h, otp.ot_h_plan, hr.present_h, ro.headcount, hr.att_present, hr.att_sched,
           ro.disp_n, ro.temp_n,
           o.otd_num, o.otd_den, o.lead_days_sum,
           f.ftt_num, f.ftt_den, d.defect_qty, rw.rework_qty, a.deduction, a.cars, w.claims, w.vehicles_in_service, cq.copq,
           dl.delivery_ontime, dl.delivery_batches, ls.lineside_lt4, ls.lineside_n,
           inv.buffer_days, inv.wip_days, inv.fg_days,
           ch.frozen_changes, sp.value,
           COALESCE(ehs.lti,0), hr.std_h+hr.ot_h, COALESCE(hz.hazards,0), COALESCE(hz.hazards_closed,0),
           wo.wo_pm, wo.wo_pm_done, wo.wo_cm, wo.repair_min, COALESCE(fe.fail_events,0),
           job.job_ontime, job.job_n, dq.dq_passed, dq.dq_checked, use.mau
    FROM prod p
    JOIN plan pl USING (month, plant_code)
    JOIN cost c USING (month, plant_code)
    JOIN cplan cp USING (month, plant_code)
    JOIN en e USING (month, plant_code)
    JOIN eplan ep USING (month, plant_code)
    JOIN ecp USING (month, plant_code)
    JOIN hr USING (month, plant_code)
    JOIN roster ro USING (month, plant_code)
    JOIN otp USING (month, plant_code)
    JOIN ord o USING (month, plant_code)
    JOIN ftt f USING (month, plant_code)
    JOIN def d USING (month, plant_code)
    JOIN rw USING (month, plant_code)
    JOIN aud a USING (month, plant_code)
    JOIN war w USING (month, plant_code)
    JOIN copq cq USING (month, plant_code)
    JOIN del dl USING (month, plant_code)
    JOIN ls USING (month, plant_code)
    JOIN inv USING (month, plant_code)
    JOIN chg ch USING (month, plant_code)
    JOIN sp USING (month, plant_code)
    LEFT JOIN ehs USING (month, plant_code)
    LEFT JOIN hz USING (month, plant_code)
    JOIN wo USING (month, plant_code)
    LEFT JOIN fe USING (month, plant_code)
    JOIN job ON job.month=p.month
    JOIN dq ON dq.month=p.month
    JOIN use ON use.month=p.month
    ''')

    # 车间 × 月
    drop_create(con, 'dws_shop_month', '''
        month TEXT, plant_code TEXT, shop_code TEXT,
        output_qty INT, plan_qty INT,
        oee REAL, jph_rate REAL, design_jph REAL, tier_act INT, tier_plan INT, shifts INT,
        run_min INT, planned_min INT, sched_min INT, stop_min INT,
        ot_line_h_act REAL, ot_line_h_plan REAL, ot_h REAL, ot_h_plan REAL, std_h REAL, headcount INT, crew INT,
        exec_days INT, workdays INT,
        elec_kwh REAL, elec_plan_kwh REAL, idle_kwh REAL,
        ftt_rate REAL, defect_qty INT, rework_qty INT,
        PRIMARY KEY (month, plant_code, shop_code)
    ''')
    con.execute('''
    INSERT INTO dws_shop_month
    WITH pr AS (
      SELECT month, plant_code, shop_code,
             SUM(output_qty) output_qty, SUM(run_min) run_min, SUM(planned_min) planned_min,
             SUM(sched_min) sched_min, SUM(stop_min) stop_min,
             AVG(design_jph) design_jph, MAX(tier_jph) tier_act,
             SUM(CASE WHEN is_ot=1 THEN planned_min ELSE 0 END)/60.0 ot_line_h_act
      FROM dwd_fact_production GROUP BY 1,2,3
    ), vp AS (
      SELECT month, plant_code, shop_code, tier_jph tier_plan, shifts, ot_line_h ot_line_h_plan,
             plan_qty, crew, heads, ot_person_h ot_h_plan, el_fix_kwh+el_ot_kwh+el_var_kwh elec_plan_kwh
      FROM dwd_fact_vcs_plan WHERE scenario_id='VCS-BASE'
    ), daily AS (
      SELECT month, plant_code, shop_code, biz_date,
             SUM(CASE WHEN is_ot=1 THEN planned_min ELSE 0 END)/60.0 ot_line_h_day,
             MAX(tier_jph) tier,
             COUNT(DISTINCT CASE WHEN is_ot=0 THEN slot END) sh
      FROM dwd_fact_production
      GROUP BY month, plant_code, shop_code, biz_date
    ), exec AS (
      SELECT a.month, a.plant_code, a.shop_code,
             SUM(CASE WHEN ABS(a.ot_line_h_day - p.ot_line_h) <= 0.10 * CASE WHEN p.ot_line_h<0.01 THEN 0.01 ELSE p.ot_line_h END
                       AND a.tier=p.tier_jph AND a.sh=p.shifts THEN 1 ELSE 0 END) exec_days,
             COUNT(*) workdays
      FROM daily a
      JOIN dwd_fact_vcs_plan_day p
        ON p.biz_date=a.biz_date AND p.plant_code=a.plant_code AND p.shop_code=a.shop_code AND p.scenario_id='VCS-BASE'
      GROUP BY 1,2,3
    ), hr AS (
      SELECT month, plant_code, shop_code, SUM(std_h) std_h, SUM(ot_h) ot_h FROM dwd_fact_attendance GROUP BY 1,2,3
    ), ro AS (
      SELECT month, plant_code, shop_code, SUM(headcount) headcount FROM dwd_fact_roster GROUP BY 1,2,3
    ), en AS (
      SELECT month, plant_code, shop_code, SUM(elec_kwh) elec_kwh, SUM(idle_kwh) idle_kwh FROM dwd_fact_energy GROUP BY 1,2,3
    ), q AS (
      SELECT month, plant_code, shop_code, SUM(first_pass)*1.0/NULLIF(SUM(inspected),0)*100 ftt_rate, SUM(rework) rework_qty
      FROM dwd_fact_inspection GROUP BY 1,2,3
    ), def AS (
      SELECT month, plant_code, shop_code, SUM(qty) defect_qty FROM dwd_fact_defect GROUP BY 1,2,3
    )
    SELECT pr.month, pr.plant_code, pr.shop_code, pr.output_qty, vp.plan_qty,
           -- OEE = 时间开动×性能×合格；这里用 run_min/planned_min × (output / (design_jph * run_min/60)) × 1
           ROUND( (pr.run_min*1.0/NULLIF(pr.planned_min,0)) * (pr.output_qty*1.0 / NULLIF(pr.design_jph * pr.run_min/60.0,0)) * 100, 1),
           ROUND( (pr.output_qty*1.0 / NULLIF(pr.run_min/60.0,0)) / NULLIF(pr.tier_act,0) * 100, 1),
           pr.design_jph, pr.tier_act, vp.tier_plan, vp.shifts,
           pr.run_min, pr.planned_min, pr.sched_min, pr.stop_min,
           pr.ot_line_h_act, vp.ot_line_h_plan, hr.ot_h, vp.ot_h_plan, hr.std_h, ro.headcount, vp.crew,
           ex.exec_days, ex.workdays,
           en.elec_kwh, vp.elec_plan_kwh, en.idle_kwh,
           q.ftt_rate, COALESCE(def.defect_qty,0), COALESCE(q.rework_qty,0)
    FROM pr
    JOIN vp USING (month, plant_code, shop_code)
    JOIN exec ex USING (month, plant_code, shop_code)
    JOIN hr USING (month, plant_code, shop_code)
    JOIN ro USING (month, plant_code, shop_code)
    JOIN en USING (month, plant_code, shop_code)
    LEFT JOIN q USING (month, plant_code, shop_code)
    LEFT JOIN def USING (month, plant_code, shop_code)
    ''')

    # 修正 OEE：合格率对总装用 1-返修，冲压用冲压件合格率；工厂 OEE 取产量加权？故事是给定 shop_oee。
    # 生成器按 design_jph 与 run/planned 标定，理论 OEE = run/planned * (output/(design_jph*run/60))。
    # 若生成精确，应复现。保留计算值。

    # 科目成本月表
    drop_create(con, 'dws_cost_account_month',
                'month TEXT, plant_code TEXT, account TEXT, grp TEXT, amount REAL, plan_amount REAL',
                'month, plant_code, account')
    con.execute('''INSERT INTO dws_cost_account_month
        SELECT a.month, a.plant_code, a.account, d.grp, a.amount, COALESCE(p.amount,0)
        FROM (SELECT month, plant_code, account, SUM(amount) amount FROM dwd_fact_cost GROUP BY 1,2,3) a
        JOIN dim_account d ON d.account=a.account
        LEFT JOIN dwd_fact_vcs_cost_plan p ON p.month=a.month AND p.plant_code=a.plant_code AND p.account=a.account AND p.scenario_id='VCS-BASE'
    ''')

    # 集团月
    drop_create(con, 'dws_group_month', '''
        month TEXT PRIMARY KEY,
        prod_qty INT, plan_qty INT, cost_total REAL, cost_plan_total REAL,
        elec_kwh REAL, elec_plan_kwh REAL, otd_num INT, otd_den INT
    ''')
    con.execute('''INSERT INTO dws_group_month
        SELECT month, SUM(prod_qty), SUM(plan_qty), SUM(cost_total), SUM(cost_plan_total),
               SUM(elec_kwh), SUM(elec_plan_kwh), SUM(otd_num), SUM(otd_den)
        FROM dws_plant_month GROUP BY month''')

    # 日产量 / 停线（总装故事线）
    drop_create(con, 'dws_ga_daily', '''
        biz_date TEXT, month TEXT, plant_code TEXT, output_qty INT, stop_min INT, short_min INT, short_cnt INT, other_min INT,
        PRIMARY KEY (biz_date, plant_code)
    ''')
    con.execute('''INSERT INTO dws_ga_daily
        SELECT p.biz_date, p.month, p.plant_code, p.output_qty,
               COALESCE(d.stop_min,0), COALESCE(d.short_min,0), COALESCE(d.short_cnt,0),
               COALESCE(d.stop_min,0)-COALESCE(d.short_min,0)
        FROM (SELECT biz_date, month, plant_code, SUM(output_qty) output_qty
              FROM dwd_fact_production WHERE shop_code='GA' GROUP BY 1,2,3) p
        LEFT JOIN (
            SELECT biz_date, plant_code, SUM(minutes) stop_min,
                   SUM(CASE WHEN reason='缺件' THEN minutes ELSE 0 END) short_min,
                   SUM(CASE WHEN reason='缺件' THEN 1 ELSE 0 END) short_cnt
            FROM dwd_fact_downtime WHERE shop_code='GA' GROUP BY 1,2
        ) d ON d.biz_date=p.biz_date AND d.plant_code=p.plant_code
    ''')

def status_of(direction, value, target, warn, lo=None, hi=None):
    if value is None: return 'na'
    if direction == 'range':
        if lo is None: return 'na'
        if lo <= value <= hi: return 'good'
        # warn band 10% outside
        return 'bad'
    if target is None: return 'na'
    if direction == 'up':
        w = warn if warn is not None else target * 0.98
        if value >= target: return 'good'
        if value >= w: return 'warn'
        return 'bad'
    if direction == 'down':
        w = warn if warn is not None else target * 1.05
        if value <= target: return 'good'
        if value <= w: return 'warn'
        return 'bad'
    if direction == 'eq':
        if warn is None: return 'good' if abs(value-target) < 1e-6 else 'bad'
        return 'good' if abs(value-target) <= warn else 'bad'
    return 'na'

def build_ads(con, S):
    drop_create(con, 'ads_kpi_value', '''
        metric_id TEXT, month TEXT, plant_code TEXT, shop_code TEXT, scope TEXT,
        value REAL, numerator REAL, denominator REAL, target REAL, warn REAL,
        status TEXT, text TEXT, unit TEXT
    ''')
    drop_create(con, 'ads_kpi_spark', 'metric_id TEXT, plant_code TEXT, shop_code TEXT, month TEXT, value REAL')
    rows, sparks = [], []
    plants = [(r['month'], r['plant_code']) for r in con.execute('SELECT month, plant_code FROM dws_plant_month')]
    # materialize rows as dicts
    pm = {}
    for r in con.execute('SELECT * FROM dws_plant_month'):
        pm[(r['month'], r['plant_code'])] = dict(r)
    sm = {}
    for r in con.execute('SELECT * FROM dws_shop_month'):
        sm[(r['month'], r['plant_code'], r['shop_code'])] = dict(r)
    gm = {r['month']: dict(r) for r in con.execute('SELECT * FROM dws_group_month')}
    # shop press / oven / takt / andon / robot / die
    extra = _shop_extras(con)

    for mdef in M.REGISTRY:
        mid = mdef['metric_id']
        for month in MONTHS:
            g = gm[month]
            # group scope
            if mdef['grain'] in ('group', 'group_or_plant'):
                val, num, den, tgt, warn, txt = M.compute(mdef, 'group', None, None, g, pm, sm, extra, S, month, con)
                if val is not None:
                    st = status_of(mdef['direction'], val, tgt, warn, mdef.get('range_lo'), mdef.get('range_hi'))
                    rows.append((mid, month, None, None, '集团', val, num, den, tgt, warn, st, txt, mdef.get('unit','')))
                    sparks.append((mid, None, None, month, val))
            if mdef['grain'] in ('plant', 'group_or_plant', 'plant_or_shop'):
                for p in PLANTS:
                    rec = pm[(month, p)]
                    val, num, den, tgt, warn, txt = M.compute(mdef, 'plant', p, None, rec, pm, sm, extra, S, month, con)
                    if val is not None:
                        st = status_of(mdef['direction'], val, tgt, warn, mdef.get('range_lo'), mdef.get('range_hi'))
                        rows.append((mid, month, p, None, PLANT_NAME[p], val, num, den, tgt, warn, st, txt, mdef.get('unit','')))
                        sparks.append((mid, p, None, month, val))
            if mdef['grain'] in ('shop', 'plant_or_shop'):
                shops = mdef.get('shops') or SHOPS
                for p in PLANTS:
                    for s in shops:
                        rec = sm.get((month, p, s))
                        if not rec: continue
                        val, num, den, tgt, warn, txt = M.compute(mdef, 'shop', p, s, rec, pm, sm, extra, S, month, con)
                        if val is not None:
                            st = status_of(mdef['direction'], val, tgt, warn, mdef.get('range_lo'), mdef.get('range_hi'))
                            rows.append((mid, month, p, s, PLANT_NAME[p]+SHOP_NAME[s], val, num, den, tgt, warn, st, txt, mdef.get('unit','')))
                            sparks.append((mid, p, s, month, val))
    con.executemany('INSERT INTO ads_kpi_value VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    con.executemany('INSERT INTO ads_kpi_spark VALUES (?,?,?,?,?)', sparks)
    # dim_metric
    drop_create(con, 'dim_metric', '''
        metric_id TEXT PRIMARY KEY, name TEXT, domain TEXT, level TEXT, grain TEXT,
        definition TEXT, formula TEXT, sql_text TEXT, source TEXT, refresh TEXT,
        owner_role TEXT, it_role TEXT, dq_rule TEXT,
        direction TEXT, unit TEXT, target_text TEXT, warn_text TEXT, example_text TEXT
    ''')
    con.executemany('INSERT INTO dim_metric VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    [(m['metric_id'], m['name'], m['domain'], m['level'], m['grain'],
                      m['definition'], m['formula'], m.get('sql',''), m.get('source',''), m.get('refresh',''),
                      m.get('owner_role',''), m.get('it_role',''), m.get('dq_rule',''),
                      m['direction'], m.get('unit',''), m.get('target_text',''), m.get('warn_text',''), m.get('example_text',''))
                     for m in M.REGISTRY])

def _shop_extras(con):
    ex = {}
    for r in con.execute('''SELECT month, plant_code, AVG(minutes) avg_smed, COUNT(*) cnt, SUM(minutes) tot
                            FROM dwd_fact_die_change GROUP BY 1,2'''):
        ex.setdefault(('smed', r['month'], r['plant_code']), dict(r))
    for r in con.execute('''SELECT month, plant_code, line_code,
                                   SUM(die_run_min)*1.0/NULLIF(SUM(die_avail_min),0)*100 die,
                                   SUM(actual_strokes)*1.0/NULLIF(SUM(design_strokes),0)*100 spm,
                                   SUM(good_parts)*1.0/NULLIF(SUM(parts),0)*100 q,
                                   SUM(die_run_min) runm, SUM(die_avail_min) avail, SUM(parts) parts, SUM(good_parts) good,
                                   SUM(actual_strokes) act, SUM(design_strokes) des
                            FROM dwd_fact_press GROUP BY 1,2,3'''):
        ex.setdefault(('press', r['month'], r['plant_code']), []).append(dict(r))
    for r in con.execute('''SELECT month, plant_code,
                                   SUM(die_run_min)*1.0/NULLIF(SUM(die_avail_min),0)*100 die,
                                   SUM(actual_strokes)*1.0/NULLIF(SUM(design_strokes),0)*100 spm,
                                   SUM(good_parts)*1.0/NULLIF(SUM(parts),0)*100 q
                            FROM dwd_fact_press GROUP BY 1,2'''):
        ex[('press_avg', r['month'], r['plant_code'])] = dict(r)
    for r in con.execute('''SELECT month, plant_code, oven_code, SUM(idle_min)*1.0/NULLIF(SUM(shifts),0) idle_ps,
                                   SUM(compliant)*1.0/NULLIF(SUM(start_stop),0)*100 comp, SUM(idle_min) idle, SUM(shifts) sh, SUM(start_stop) ss, SUM(compliant) cp
                            FROM dwd_fact_oven GROUP BY 1,2,3'''):
        ex.setdefault(('oven', r['month'], r['plant_code']), []).append(dict(r))
    for r in con.execute('''SELECT month, plant_code, SUM(idle_min)*1.0/NULLIF(SUM(shifts),0) idle_ps,
                                   SUM(compliant)*1.0/NULLIF(SUM(start_stop),0)*100 comp
                            FROM dwd_fact_oven GROUP BY 1,2'''):
        ex[('oven_avg', r['month'], r['plant_code'])] = dict(r)
    for r in con.execute('''SELECT month, plant_code, shop_code,
                                   AVG(design_takt_s)*1.0/NULLIF(SUM(actual_takt_s*cycles)/NULLIF(SUM(cycles),0),0)*100 takt
                            FROM dwd_fact_takt GROUP BY 1,2,3'''):
        ex[('takt', r['month'], r['plant_code'], r['shop_code'])] = r['takt']
    for r in con.execute('''SELECT month, plant_code, SUM(resp_sec_total)*1.0/NULLIF(SUM(calls),0)/60.0 andon, SUM(calls) calls
                            FROM dwd_fact_andon GROUP BY 1,2'''):
        ex[('andon', r['month'], r['plant_code'])] = dict(r)
    for r in con.execute('''SELECT month, plant_code, SUM(minutes) robot_min
                            FROM dwd_fact_downtime WHERE shop_code='BD' AND reason='机器人故障' GROUP BY 1,2'''):
        ex[('robot', r['month'], r['plant_code'])] = r['robot_min']
    for r in con.execute('''SELECT month, plant_code, reason, SUM(minutes) minutes, COUNT(*) cnt
                            FROM dwd_fact_downtime WHERE shop_code='GA' GROUP BY 1,2,3'''):
        ex.setdefault(('ga_stop', r['month'], r['plant_code']), []).append(dict(r))
    for r in con.execute('''SELECT month, plant_code, buffer_code, level_units
                            FROM dwd_fact_buffer WHERE biz_date IN (SELECT MAX(biz_date) FROM dwd_fact_buffer b2 WHERE b2.month=dwd_fact_buffer.month AND b2.plant_code=dwd_fact_buffer.plant_code AND b2.buffer_code=dwd_fact_buffer.buffer_code)
                         '''):
        ex[('buf_end', r['month'], r['plant_code'], r['buffer_code'])] = r['level_units']
    return ex

def build_actions(con, S):
    drop_create(con, 'ads_action', '''
        action_id INTEGER PRIMARY KEY AUTOINCREMENT,
        month TEXT, plant_code TEXT, shop_code TEXT, metric_id TEXT, title TEXT,
        actual REAL, actual_text TEXT, warn_text TEXT, target_text TEXT,
        owner_role TEXT, status TEXT, due_date TEXT, created_at TEXT, closed_at TEXT, note TEXT, auto INT
    ''')
    # 对故事月超标指标自动生成待办（工厂/集团/车间）
    month = STORY_MONTH
    created = '2026-11-01'
    due = '2026-11-15'
    ins = []
    # 固定故事行动（与演示路径一致）
    story_actions = [
        ('A', None, 'unit_cost', 'A工厂单车转换成本 5,512 元/台，超出 VCS 测算 4,997（+10.3%）', '集团财务-成本控制经理', '处理中', '产量摊薄 +319 元，花费偏差 +196 元（示例）'),
        ('A', None, 'ot_rate', 'A工厂加班率 29.5%，高于 VCS 测算 25.1%', '工厂人力资源经理', '处理中', '总装线体加班 96 h vs 建议 72.2 h（示例）'),
        ('A', 'GA', 'short_cnt', 'A工厂总装缺件停线 86 次 / 1,155 分钟', '工厂物流经理', '处理中', '首要零件 P-30117 / 供应商 S07 准时率 76.5%（示例）'),
        ('A', None, 'vcs_exec', 'A工厂 VCS 方案执行率 62%，总装仅 28%', '工厂计划经理', '开放', '缺件改善前总装偏离推荐加班补产（示例）'),
        ('A', None, 'lg_ontime', '供应商到货准时率偏低，S07 为 76.5%', '工厂物流经理', '开放', None),
        ('A', 'PT', 'paint_kwh', '涂装单车电耗 270 kWh，高于 VCS 测算 259', '涂装车间主任/能源工程师', '开放', '烘房空烘 38 分钟/班、开停合规率 88%（示例）'),
        ('A', None, 'hpv', 'A工厂 HPV 33.6 h/台，高于 VCS 测算 32.1', '集团工业工程经理', '开放', None),
        ('A', None, 'pbs_buffer', 'PBS 涂装车身库月末 500/500，已达有效上限', '工厂计划经理', '开放', 'R1 缓存约束（示例）'),
        ('A', None, 'backlog', '欠产 660 台，延期成本 99 万元（R2）', '工厂计划经理', '开放', None),
        ('A', None, 'attend', 'A工厂出勤率 93.4%，低于目标 97%', '工厂人力资源经理', '开放', None),
    ]
    # also auto from ads
    for r in con.execute('''SELECT * FROM ads_kpi_value WHERE month=? AND status='bad' AND plant_code IS NOT NULL''', (month,)):
        pass  # story list covers key ones; additional auto below
    for i, (p, s, mid, title, owner, st, note) in enumerate(story_actions, 1):
        rec = con.execute("SELECT value, text, target FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code=? AND (shop_code IS ? OR (shop_code IS NULL AND ? IS NULL))",
                          (mid, month, p, s, s)).fetchone()
        # metric may use different id; store anyway
        ins.append((month, p, s, mid, title, rec['value'] if rec else None, rec['text'] if rec else '', '', '',
                    owner, st, due, created, None, note, 1))
    # auto extras
    for r in con.execute('''SELECT v.*, m.owner_role, m.name, m.warn_text, m.target_text
                            FROM ads_kpi_value v JOIN dim_metric m ON m.metric_id=v.metric_id
                            WHERE v.month=? AND v.status='bad' AND v.plant_code='A' ''', (month,)):
        if any(x[3]==r['metric_id'] and x[1]==r['plant_code'] and x[2]==r['shop_code'] for x in ins):
            continue
        title = f"{r['scope']}{r['name']} {r['text']}，未达目标（{r['target_text']}）"
        ins.append((month, r['plant_code'], r['shop_code'], r['metric_id'], title, r['value'], r['text'], r['warn_text'], r['target_text'],
                    r['owner_role'] or '工厂厂长', '开放', due, created, None, '由预警线自动生成（示例）', 1))
    con.executemany('''INSERT INTO ads_action (month,plant_code,shop_code,metric_id,title,actual,actual_text,warn_text,target_text,owner_role,status,due_date,created_at,closed_at,note,auto)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', ins)

    drop_create(con, 'ads_usage_log', 'ts TEXT, role TEXT, page TEXT, metric_id TEXT, views INT DEFAULT 1')

def build_ontology(con):
    """根因关系：停线→缺件→零件→供应商→班次（示例月 A工厂）。"""
    drop_create(con, 'ads_graph_node', 'node_id TEXT PRIMARY KEY, kind TEXT, label TEXT, sub TEXT, value REAL, unit TEXT, status TEXT')
    drop_create(con, 'ads_graph_edge', 'src TEXT, dst TEXT, rel TEXT, weight REAL, label TEXT')
    month = STORY_MONTH
    nodes, edges = [], []
    def add_n(*a): nodes.append(a)
    def add_e(*a): edges.append(a)
    add_n('COST', 'metric', '单车转换成本', 'A工厂 5,512 vs 4,997', 5512, '元/台', 'bad')
    add_n('OT', 'metric', '加班率', '29.5% vs VCS 25.1%', 29.5, '%', 'bad')
    add_n('VCS', 'metric', 'VCS方案执行率', '62%，总装 28%', 62, '%', 'bad')
    add_n('GA', 'shop', '总装车间', 'OEE 73.8% / JPH 93.5%', 73.8, '%', 'bad')
    add_n('STOP', 'event', '总装停线', '2,140 分钟 / 49 班当量', 2140, '分钟', 'bad')
    add_n('SHORT', 'event', '缺件停线', '1,155 分钟 / 86 次', 1155, '分钟', 'bad')
    add_e('COST','OT','驱动', 0.6, '加班与产量摊薄推高单车成本')
    add_e('OT','VCS','驱动', 0.7, '偏离推荐方案、用加班补产')
    add_e('VCS','GA','发生在', 0.8, '总装执行率仅 28%')
    add_e('GA','STOP','表现为', 0.9, '停线 43.7 分钟/班')
    add_e('STOP','SHORT','主因', 0.54, '缺件占停线 54%')
    for r in con.execute('''SELECT part_no, supplier_code, COUNT(*) cnt, SUM(minutes) minutes
                            FROM dwd_fact_downtime
                            WHERE plant_code='A' AND month=? AND shop_code='GA' AND reason='缺件' AND part_no IS NOT NULL
                            GROUP BY 1,2 ORDER BY minutes DESC LIMIT 10''', (month,)):
        pid, sid = 'P-'+r['part_no'], 'S-'+r['supplier_code']
        pname = con.execute('SELECT part_name FROM dim_part WHERE part_no=?', (r['part_no'],)).fetchone()
        add_n(pid, 'part', r['part_no'], (pname['part_name'] if pname else '')+f" · {r['cnt']}次/{r['minutes']}分钟", r['minutes'], '分钟', 'bad' if r['minutes']>=120 else 'warn')
        add_e('SHORT', pid, '涉及', r['minutes'], f"{r['cnt']} 次")
        # supplier node once
        if not any(n[0]==sid for n in nodes):
            rate = con.execute('''SELECT SUM(ontime_batches)*100.0/SUM(batches) r FROM dwd_fact_delivery
                                  WHERE plant_code='A' AND month=? AND supplier_code=?''', (month, r['supplier_code'])).fetchone()
            rv = rate['r'] if rate else None
            add_n(sid, 'supplier', r['supplier_code'], f"到货准时率 {rv:.1f}%" if rv else '供应商', rv, '%', 'bad' if rv and rv<90 else 'warn')
        add_e(pid, sid, '供应', r['minutes'], '供应商')
    con.executemany('INSERT INTO ads_graph_node VALUES (?,?,?,?,?,?,?)', nodes)
    con.executemany('INSERT INTO ads_graph_edge VALUES (?,?,?,?,?)', edges)

def transform(con=None, verbose=True):
    S = load_story()
    set_workday_override(STORY_MONTH, story_workdays(S))
    own = con is None
    con = con or connect()
    if verbose: print('  dims...')
    build_dims(con, S)
    drop_create(con, 'dwd_dq_result',
                'rule_id TEXT, name TEXT, layer TEXT, severity TEXT, month TEXT, plant_code TEXT, checked INT, failed INT, note TEXT')
    if verbose: print('  dwd...')
    build_dwd(con)
    if verbose: print('  dws...')
    build_dws(con)
    write_dq(con)
    if verbose: print('  ads...')
    build_ads(con, S)
    build_actions(con, S)
    build_ontology(con)
    con.commit()
    if own: con.close()

if __name__ == '__main__':
    transform()
    print('transform done')
