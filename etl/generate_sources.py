"""ODS 生成器：模拟 MES / ERP / WMS / QMS / EMS(能源计量) / HR / VCS / CMMS / EHS / BI 日志 等源系统抽取。
确定性（固定 seed），按 targets.py 的月度锚点“自上而下分配”到日 / 班 / 事件粒度，保证 ETL 重算可复现示例数字。
另外故意注入少量脏数据（重复、空编码、负值、越界），用于演示 DWD 层数据质量规则（隔离后不影响对账）。
所有数据均为示例数据。
"""
import datetime as dt, math
from .common import *
from .targets import build_targets

ODS_DDL = {
 # ---------- 主数据 ----------
 'ods_md_plant': 'plant_code TEXT, plant_name TEXT, region TEXT, start_year INT',
 'ods_md_shop': 'shop_code TEXT, shop_name TEXT, seq INT, shop_type TEXT',
 'ods_md_supplier': 'supplier_code TEXT, supplier_name TEXT, category TEXT, region TEXT',
 'ods_md_part': 'part_no TEXT, part_name TEXT, supplier_code TEXT, commodity TEXT, is_key INT',
 'ods_md_defect': 'defect_code TEXT, defect_name TEXT, shop_code TEXT, defect_group TEXT',
 'ods_md_equipment': 'equip_code TEXT, plant_code TEXT, shop_code TEXT, equip_name TEXT, equip_type TEXT, is_critical INT',
 # ---------- VCS（产量成本测算）----------
 'ods_vcs_jph_tier': 'plant_code TEXT, shop_code TEXT, tier_jph INT, heads_direct INT, heads_indirect INT, run_kw INT, valid_from TEXT',
 'ods_vcs_shift_pattern': 'pattern_code TEXT, pattern_name TEXT, shifts_per_day INT, hours_per_shift REAL, night_shift INT, note TEXT',
 'ods_vcs_plan_month': 'scenario_id TEXT, version TEXT, month TEXT, plant_code TEXT, shop_code TEXT, tier_jph INT, shifts INT, pattern_code TEXT, ot_line_h REAL, crew INT, heads INT, ot_person_h INT, plan_qty INT, el_fix_kwh REAL, el_ot_kwh REAL, el_var_kwh REAL',
 'ods_vcs_plan_day': 'scenario_id TEXT, version TEXT, biz_date TEXT, plant_code TEXT, shop_code TEXT, tier_jph INT, shifts INT, ot_line_h REAL',
 'ods_vcs_cost_plan': 'scenario_id TEXT, version TEXT, month TEXT, plant_code TEXT, account TEXT, amount REAL',
 'ods_vcs_buffer_plan': 'scenario_id TEXT, month TEXT, plant_code TEXT, buffer_code TEXT, cap_units INT, cap_effective INT, plan_end INT',
 'ods_vcs_scenario': 'scenario_id TEXT, scenario_name TEXT, scenario_type TEXT, metric TEXT, value REAL, unit TEXT, note TEXT',
 # ---------- MES ----------
 'ods_mes_shift_run': 'run_id TEXT, biz_date TEXT, plant_code TEXT, shop_code TEXT, slot TEXT, tier_jph INT, design_jph REAL, sched_min INT, planned_min INT, stop_min INT, minor_stop_min INT, output_qty INT, load_ts TEXT',
 'ods_mes_downtime': 'event_id TEXT, biz_date TEXT, plant_code TEXT, shop_code TEXT, slot TEXT, equip_code TEXT, reason TEXT, minutes INT, part_no TEXT, supplier_code TEXT, load_ts TEXT',
 'ods_mes_die_change': 'event_id TEXT, biz_date TEXT, plant_code TEXT, line_code TEXT, minutes REAL',
 'ods_mes_press_daily': 'biz_date TEXT, plant_code TEXT, line_code TEXT, die_avail_min INT, die_run_min INT, design_strokes INT, actual_strokes INT, parts INT, good_parts INT',
 'ods_mes_oven_daily': 'biz_date TEXT, plant_code TEXT, oven_code TEXT, shifts INT, idle_min INT, start_stop INT, compliant INT',
 'ods_mes_takt_daily': 'biz_date TEXT, plant_code TEXT, shop_code TEXT, design_takt_s REAL, actual_takt_s REAL, cycles INT',
 'ods_mes_andon_daily': 'biz_date TEXT, plant_code TEXT, calls INT, resp_sec_total INT',
 'ods_mes_buffer_daily': 'biz_date TEXT, plant_code TEXT, buffer_code TEXT, level_units INT',
 # ---------- QMS ----------
 'ods_qms_defect': 'rec_id TEXT, biz_date TEXT, plant_code TEXT, shop_code TEXT, defect_code TEXT, qty INT',
 'ods_qms_inspection': 'biz_date TEXT, plant_code TEXT, shop_code TEXT, inspected INT, first_pass INT, rework INT',
 'ods_qms_vehicle_ftt': 'biz_date TEXT, plant_code TEXT, offline INT, first_pass INT',
 'ods_qms_audit': 'month TEXT, plant_code TEXT, cars INT, deduction REAL',
 'ods_qms_warranty': 'month TEXT, plant_code TEXT, claims INT, vehicles_in_service INT',
 'ods_qms_copq': 'month TEXT, plant_code TEXT, category TEXT, amount REAL',
 # ---------- WMS / 物流 ----------
 'ods_wms_delivery': 'rec_id TEXT, biz_date TEXT, plant_code TEXT, supplier_code TEXT, batches INT, ontime_batches INT',
 'ods_wms_lineside': 'snapshot_date TEXT, plant_code TEXT, part_no TEXT, buffer_h REAL',
 'ods_wms_inventory': 'biz_date TEXT, plant_code TEXT, inv_type TEXT, qty INT, daily_demand REAL',
 # ---------- ERP ----------
 'ods_erp_order': 'order_id TEXT, plant_code TEXT, order_date TEXT, promise_date TEXT, ship_date TEXT, qty INT',
 'ods_erp_cost': 'month TEXT, plant_code TEXT, cost_center TEXT, account TEXT, amount REAL',
 'ods_erp_spare': 'month TEXT, plant_code TEXT, value REAL',
 'ods_aps_plan_daily': 'biz_date TEXT, plant_code TEXT, plan_qty INT, version TEXT',
 'ods_aps_change': 'change_id TEXT, plant_code TEXT, shop_code TEXT, change_date TEXT, in_frozen INT, reason TEXT',
 # ---------- 能源计量 ----------
 'ods_ems_daily': 'biz_date TEXT, plant_code TEXT, shop_code TEXT, fix_kwh REAL, ot_kwh REAL, var_kwh REAL, idle_kwh REAL, peak_kwh REAL, flat_kwh REAL, valley_kwh REAL, cost REAL, water_m3 REAL',
 # ---------- HR ----------
 'ods_hr_roster': 'month TEXT, plant_code TEXT, shop_code TEXT, emp_type TEXT, headcount INT',
 'ods_hr_attendance': 'biz_date TEXT, plant_code TEXT, shop_code TEXT, scheduled INT, present INT, std_h REAL, ot_h REAL',
 # ---------- CMMS 设备维护 ----------
 'ods_cmms_wo': 'wo_id TEXT, plant_code TEXT, shop_code TEXT, equip_code TEXT, wo_type TEXT, planned_date TEXT, done_date TEXT, repair_min INT, event_id TEXT',
 # ---------- EHS ----------
 'ods_ehs_incident': 'incident_id TEXT, biz_date TEXT, plant_code TEXT, shop_code TEXT, inc_type TEXT, lost_days INT',
 'ods_ehs_hazard': 'hazard_id TEXT, plant_code TEXT, shop_code TEXT, raised_date TEXT, closed_date TEXT, level TEXT',
 # ---------- 平台日志 ----------
 'ods_sys_job_run': 'run_id TEXT, dag_id TEXT, task_id TEXT, biz_date TEXT, sla_ts TEXT, end_ts TEXT, status TEXT',
 'ods_sys_dq_history': 'biz_date TEXT, rule_id TEXT, checked INT, passed INT',
 'ods_bi_usage': 'biz_date TEXT, user_id TEXT, role TEXT, page TEXT, views INT',
}

def create_ods(con):
    for t, cols in ODS_DDL.items():
        con.execute(f'DROP TABLE IF EXISTS {t}')
        con.execute(f'CREATE TABLE {t} ({cols})')

def ins(con, table, rows):
    if not rows: return
    n = len(rows[0])
    con.executemany(f'INSERT INTO {table} VALUES ({",".join("?" * n)})', rows)

LOAD_TS = '2026-11-01 02:15:00'

# ---------------- 主数据 ----------------
def gen_master(con, S):
    ins(con, 'ods_md_plant', [('A', 'A工厂', '华东', 2013), ('B', 'B工厂', '华东', 2016), ('C', 'C工厂', '西南', 2019)])
    ins(con, 'ods_md_shop', [('ST', '冲压', 1, '车间'), ('BD', '焊装', 2, '车间'), ('PT', '涂装', 3, '车间'), ('GA', '总装', 4, '车间')])
    cats = {'S01': '车身件', 'S02': '电子电器', 'S03': '座椅', 'S04': '底盘', 'S05': '外饰', 'S06': '动力总成', 'S07': '线束',
            'S08': '标准件', 'S09': '安全系统', 'S10': '空调', 'S11': '内饰', 'S12': '玻璃', 'S13': '灯具', 'S14': '轮胎'}
    ins(con, 'ods_md_supplier', [(s, '供应商' + s, cats[s], '华东' if i % 3 else '华南') for i, (s, _, _) in enumerate(S['suppliers'])])
    # 关键零件：故事 Top10 + 生成的 190 个
    parts = [(p[0], p[1], p[2], cats[p[2]], 1) for p in S['parts']]
    used = {p[0] for p in parts}
    r = rng('parts')
    names = ['支架', '线束', '饰板', '传感器', '密封条', '卡扣组件', '管路', '模块', '总成', '护板']
    sup = [s[0] for s in S['suppliers']]
    while len(parts) < 200:
        no = 'P-%05d' % r.randint(10000, 79999)
        if no in used: continue
        used.add(no); sc = r.choice(sup)
        parts.append((no, cats[sc] + r.choice(names), sc, cats[sc], 1))
    ins(con, 'ods_md_part', parts)
    dset = []
    code = {}
    for i, (name, shopn) in enumerate([(d[0], d[1]) for d in S['q_def']]):
        sc = SHOP_CODE[shopn]
        if name == '色差/打磨印':
            for j, nm in enumerate(['色差', '打磨印']):
                c = f'D{sc}{i:02d}{j}'; dset.append((c, nm, sc, '色差/打磨印')); code[(nm, sc)] = c
        else:
            c = f'D{sc}{i:02d}'; dset.append((c, name, sc, name)); code[(name, sc)] = c
    ins(con, 'ods_md_defect', dset)
    eq = []
    robots = [x[0] for x in S['bd_robot']] + ['R-UB-%02d' % i for i in (1, 2, 5, 6)] + ['R-SR-%02d' % i for i in (1, 2, 3)] + ['R-FR-%02d' % i for i in (2, 4)]
    for p in PLANTS:
        for l in S['st_lines']: eq.append((f'{p}-ST-{l}', p, 'ST', f'压机线{l}', '压机线', 1))
        for rb in robots: eq.append((f'{p}-BD-{rb}', p, 'BD', f'焊接机器人{rb}', '机器人', 1 if rb in [x[0] for x in S['bd_robot'][:6]] else 0))
        eq.append((f'{p}-BD-FIX', p, 'BD', '夹具系统', '夹具', 1)); eq.append((f'{p}-BD-CNV', p, 'BD', '车身输送', '输送', 1))
        for i, o in enumerate(S['pt_ovens']): eq.append((f'{p}-PT-OV{i+1}', p, 'PT', o, '烘房', 1))
        for nm, c in [('输送链', 'CNV'), ('喷涂机器人', 'RBT'), ('前处理/电泳', 'ED')]: eq.append((f'{p}-PT-{c}', p, 'PT', nm, nm, 1))
        for nm, c in [('内饰线', 'TR'), ('底盘线', 'CH'), ('最终线', 'FN'), ('拧紧设备', 'TQ'), ('加注设备', 'FL')]: eq.append((f'{p}-GA-{c}', p, 'GA', nm, '装配线' if c in ('TR', 'CH', 'FN') else '工艺设备', 1))
    ins(con, 'ods_md_equipment', eq)
    ins(con, 'ods_vcs_shift_pattern', [('P0', '停线（0 班）', 0, 0, 0, 'R3：整月停线仍发生固定成本'), ('P1', '单班 1×8h', 1, 8, 0, ''),
                                       ('P2', '两班 2×8h', 2, 8, 0, 'VCS 推荐常用模式'), ('P3', '三班 3×8h', 3, 8, 1, '含夜班补贴'), ('P2L', '两班 2×12h', 2, 12, 1, 'v5.2 待扩展')])
    return code, robots

# ---------------- 主生成 ----------------
def generate(con=None, verbose=True):
    S = load_story()
    T = build_targets(S)
    own = con is None
    con = con or connect()
    create_ods(con)
    defect_code, robots = gen_master(con, S)
    tiers_rows = []
    for p in PLANTS:
        t = T[(p, STORY_MONTH)]
        for s in SHOPS:
            d = t['shop'][s]
            for tj in d['tiers']:
                ratio = tj / d['tier_plan']
                tiers_rows.append((p, s, tj, int(round(d['heads_shift'] * ratio)), int(round(d['ind_shift'] * (0.5 + 0.5 * ratio))), int(round(d['run_kw'] * (0.6 + 0.4 * ratio))), '2025-01-01'))
    ins(con, 'ods_vcs_jph_tier', tiers_rows)
    parts = [dict(zip(['no', 'name', 'sup'], r)) for r in con.execute('SELECT part_no, part_name, supplier_code FROM ods_md_part').fetchall()]
    story_parts = {x[0]: x for x in S['parts']}
    sup_rate_story = {x[0]: x[1] for x in S['suppliers']}
    sup_batches_story = {x[0]: x[2] for x in S['suppliers']}
    ev_seq = [0]
    def eid(prefix):
        ev_seq[0] += 1; return f'{prefix}{ev_seq[0]:07d}'
    for m in MONTHS:
        wds = workdays(m); days = list(month_days(m))
        for p in PLANTS:
            t = T[(p, m)]; r = rng('gen', p, m); A_story = (p == 'A' and m == STORY_MONTH); w = t['w']
            wd = len(wds)
            # ---------- 计划（APS 冻结版）与 VCS 月度方案 ----------
            plan_day = alloc_int(t['plan'], noisy_weights(r, wd, 0.04))
            ins(con, 'ods_aps_plan_daily', [(d.isoformat(), p, q, 'FROZEN') for d, q in zip(wds, plan_day)])
            n_chg = int(round(_ := (4 + 14 * w) * (1 + r.uniform(-0.2, 0.2))))
            chg = []
            for i in range(n_chg + int(3 + r.random() * 4)):
                d = r.choice(wds); chg.append((f'CHG-{p}-{m}-{i:03d}', p, r.choice(SHOPS), d.isoformat(), 1 if i < n_chg else 0, r.choice(['物料短缺', '订单插单', '设备异常', '质量冻结', '车型切换'])))
            ins(con, 'ods_aps_change', chg)
            vm, vd, vc = [], [], []
            el_plan_tot = {}
            for s in SHOPS:
                d = t['shop'][s]; e = t['en'][s]
                fix_plan = e['plan'] - e['var'] - d['run_kw'] * d['ot_line_plan'] / t['plan']
                el_plan_tot[s] = e['plan'] * t['plan']
                vm.append(('VCS-BASE', 'v5.2', m, p, s, d['tier_plan'], d['shifts'], 'P%d' % d['shifts'], d['ot_line_plan'], d['crew'], d['head'], d['ot_h_plan'], t['plan'],
                           round(fix_plan * t['plan'], 1), round(d['run_kw'] * d['ot_line_plan'], 1), round(e['var'] * t['plan'], 1)))
            ins(con, 'ods_vcs_plan_month', vm)
            ins(con, 'ods_vcs_cost_plan', [('VCS-BASE', 'v5.2', m, p, k, round(v, 2)) for k, v in t['acc_plan'].items()])
            # ---------- 车间：日级 VCS 计划 vs 实际（执行一致性）+ 班次运行 ----------
            out_by_day = {}
            for s in SHOPS:
                d = t['shop'][s]; rs = rng('shop-gen', p, m, s)
                pw = noisy_weights(rs, wd, 0.25)
                ot_plan_d = alloc_float(d['ot_line_plan'], pw, 2)
                matched = set(rs.sample(range(wd), d['exec_days']))
                act = [0.0] * wd
                for i in range(wd):
                    if i in matched: act[i] = round(ot_plan_d[i] * (1 + rs.uniform(-0.04, 0.04)), 2)
                R = round(d['ot_line_act'] - sum(act[i] for i in matched), 2)
                um = [i for i in range(wd) if i not in matched]
                if um:
                    dev = []; acc = 0.0; target = R - sum(ot_plan_d[i] for i in um)
                    for i in um:
                        step = 0.25 * ot_plan_d[i]
                        sgn = 1 if acc < target else -1
                        dev.append(sgn * step); acc += sgn * step
                    rem = target - acc
                    same = [k for k, v in enumerate(dev) if (v > 0) == (rem > 0)] or list(range(len(dev)))
                    tot_same = sum(ot_plan_d[um[k]] for k in same) or 1
                    for k in same: dev[k] += rem * ot_plan_d[um[k]] / tot_same
                    for k, i in enumerate(um): act[i] = round(max(0.0, ot_plan_d[i] + dev[k]), 2)
                    act[um[-1]] = round(act[um[-1]] + d['ot_line_act'] - sum(act), 2)
                else:
                    act[-1] = round(act[-1] + d['ot_line_act'] - sum(act), 2)
                d['_ot_act_day'] = act; d['_ot_plan_day'] = ot_plan_d
                vd += [('VCS-BASE', 'v5.2', wds[i].isoformat(), p, s, d['tier_plan'], d['shifts'], ot_plan_d[i]) for i in range(wd)]
                # ---- 班次运行标定 ----
                G = t['prod']; j = d['jph'] / 100; o = d['oee'] / 100; Tj = d['tier_act']
                S_tot = sum(v for _, v in d['stops'])
                RM = G * 60 / (Tj * j)
                d['_RM'] = RM; d['_S'] = S_tot
            # 班次利用率（开动时间 ÷ 计划生产时间）四车间合计 = 目标 → 统一放大系数 μ
            sumRM = sum(t['shop'][s]['_RM'] for s in SHOPS); sumRS = sum(t['shop'][s]['_RM'] + t['shop'][s]['_S'] for s in SHOPS)
            mu = max(1.005, sumRM / (t['shift_util'] / 100) / sumRS)
            runs = []; downs = []
            for s in SHOPS:
                d = t['shop'][s]; rs = rng('runs', p, m, s)
                G = t['prod']; o = d['oee'] / 100; Tj = d['tier_act']
                PM = (d['_RM'] + d['_S']) * mu
                D = G * 60 / (o * PM)
                d['design_jph'] = D
                PM_i = int(round(PM)); RM_i = int(round(d['_RM'])); minor = PM_i - RM_i - d['_S']
                ot_min = [int(round(h * 60)) for h in d['_ot_act_day']]
                reg_tot = PM_i - sum(ot_min)
                slots = []
                for i, day in enumerate(wds):
                    for sl in SLOTS[:d['shifts']]: slots.append((day, sl, 480, 1.0 + rs.uniform(-0.03, 0.03)))
                    if ot_min[i] > 0: slots.append((day, 'OT', int(round(d['_ot_act_day'][i] * 60)), None))
                reg_idx = [k for k, x in enumerate(slots) if x[1] != 'OT']
                reg_alloc = alloc_int(reg_tot, [slots[k][3] for k in reg_idx])
                planned = [0] * len(slots); oi = 0
                for k, x in enumerate(slots):
                    if x[1] == 'OT':
                        planned[k] = ot_min[wds.index(x[0])]
                for k, v in zip(reg_idx, reg_alloc): planned[k] = v
                # 停线事件分配到班次
                stop_k = [0] * len(slots)
                ev = []
                reasons = d['stops']
                for reason, mins in reasons:
                    if mins <= 0: continue
                    if s == 'GA' and reason == '缺件':
                        ev += gen_shortage_events(S, t, p, m, rs, mins, story_parts, parts, sup_rate_story, A_story)
                    elif s == 'BD' and reason == '机器人故障':
                        rob = [(rb, v) for rb, v in S['bd_robot']]
                        if A_story:
                            rest = mins - sum(v for _, v in rob)
                            others = [rb for rb in robots if rb not in dict(rob)]
                            extra = alloc_int(rest, noisy_weights(rs, len(others), 0.4))
                            alloc = rob + list(zip(others, extra))
                        else:
                            vals = alloc_int(mins, [v * (0.6 + 0.8 * rs.random()) for _, v in rob] + [20] * 9)
                            alloc = list(zip([x for x, _ in rob] + [rb for rb in robots if rb not in dict(rob)], vals))
                        for rb, v in alloc:
                            if v <= 0: continue
                            n = max(1, int(round(v / 14)))
                            for mm in alloc_int(v, noisy_weights(rs, n, 0.5)):
                                if mm > 0: ev.append((reason, mm, f'{p}-BD-{rb}', None, None))
                    else:
                        n = max(1, int(round(mins / {'ST': 18, 'BD': 22, 'PT': 20, 'GA': 13}[s])))
                        eqs = [e for e in equip_for(s, reason, p)]
                        for mm in alloc_int(mins, noisy_weights(rs, n, 0.5)):
                            if mm > 0: ev.append((reason, mm, rs.choice(eqs), None, None))
                order = list(range(len(slots)))
                for (reason, mm, eq, part, sup) in ev:
                    # 分配到剩余开动时间足够的班次
                    for _try in range(50):
                        k = rs.choice(order)
                        if planned[k] - stop_k[k] - mm > 60: break
                    stop_k[k] += mm
                    downs.append((eid('DT'), slots[k][0].isoformat(), p, s, slots[k][1], eq, reason, mm, part, sup, LOAD_TS))
                avail = [planned[k] - stop_k[k] for k in range(len(slots))]
                minor_k = alloc_int(minor, [max(1, a) for a in avail])
                run = [avail[k] - minor_k[k] for k in range(len(slots))]
                out = alloc_int(G, [max(0, x) * Tj for x in run])
                sched_scale = 1.0
                for k, x in enumerate(slots):
                    sched = x[2] if x[1] != 'OT' else int(round(d['_ot_act_day'][wds.index(x[0])] * 60))
                    runs.append((f'R{p}{s}{x[0].strftime("%Y%m%d")}{x[1]}', x[0].isoformat(), p, s, x[1], Tj, round(D, 3), sched, planned[k], stop_k[k], minor_k[k], out[k], LOAD_TS))
                    out_by_day.setdefault((s, x[0]), 0)
                    out_by_day[(s, x[0])] += out[k]
            # 脏数据注入：重复班次记录 + 负停机
            if runs:
                runs.append(runs[r.randrange(len(runs))])
                downs.append((eid('DT'), wds[0].isoformat(), p, 'GA', 'S1', f'{p}-GA-FN', None, 12, None, None, LOAD_TS))
                downs.append((eid('DT'), wds[1].isoformat(), p, 'BD', 'S2', f'{p}-BD-CNV', '输送', -5, None, None, LOAD_TS))
            ins(con, 'ods_mes_shift_run', runs); ins(con, 'ods_mes_downtime', downs)
            ins(con, 'ods_vcs_plan_day', vd)
            gen_shop_details(con, S, T, p, m, wds, out_by_day, r, A_story, eid)
            gen_quality(con, S, t, p, m, wds, out_by_day, r, A_story, defect_code, eid)
            gen_logistics(con, S, t, p, m, wds, days, r, A_story, parts, story_parts, sup_rate_story, sup_batches_story, eid)
            gen_energy(con, S, t, p, m, wds, out_by_day, r, A_story)
            gen_hr(con, S, t, p, m, wds, r, A_story)
            gen_cost(con, S, t, p, m, r)
            gen_maint_safety(con, S, t, p, m, wds, r, eid)
            gen_buffers(con, S, t, p, m, wds, r, A_story)
        if verbose: print('  ods', m, 'ok')
    gen_vcs_scenarios(con, S)
    gen_platform_logs(con, S)
    con.commit()
    if own: con.close()
    return T

def equip_for(s, reason, p):
    return {'ST': [f'{p}-ST-L{i}' for i in range(1, 5)], 'BD': [f'{p}-BD-FIX', f'{p}-BD-CNV'],
            'PT': [f'{p}-PT-CNV', f'{p}-PT-RBT', f'{p}-PT-ED', f'{p}-PT-OV1', f'{p}-PT-OV2', f'{p}-PT-OV3'],
            'GA': [f'{p}-GA-TR', f'{p}-GA-CH', f'{p}-GA-FN', f'{p}-GA-TQ', f'{p}-GA-FL']}[s]

def gen_shortage_events(S, t, p, m, rs, mins, story_parts, parts, sup_rate, A_story):
    """缺件停线事件：故事月严格复现 Top10 零件（次数/分钟）与总次数 86 / 总分钟 1,155。"""
    ev = []
    if A_story:
        top = S['parts']
        for no, name, sup, cnt, mm, _, _ in top:
            for x in alloc_int(mm, noisy_weights(rs, cnt, 0.35)): ev.append(('缺件', x, f'{p}-GA-FN', no, sup))
        rest_cnt = S['short_cnt'] - sum(x[3] for x in top); rest_min = mins - sum(x[4] for x in top)
        pool = [q for q in parts if q['no'] not in story_parts]
        for x in alloc_int(rest_min, noisy_weights(rs, rest_cnt, 0.3)):
            q = rs.choice(pool); ev.append(('缺件', x, f'{p}-GA-FN', q['no'], q['sup']))
    else:
        n = max(1, int(round(mins / 13.4)))
        wts = [(100 - sup_rate[q['sup']]) ** (1 + 2 * t['w']) * (3 if q['no'] in story_parts else 1) for q in parts]
        tot = sum(wts)
        for x in alloc_int(mins, noisy_weights(rs, n, 0.35)):
            u = rs.random() * tot; acc = 0
            for q, wv in zip(parts, wts):
                acc += wv
                if acc >= u: break
            ev.append(('缺件', x, f'{p}-GA-FN', q['no'], q['sup']))
    return [e for e in ev if e[1] > 0]

def gen_shop_details(con, S, T, p, m, wds, out_by_day, r, A_story, eid):
    t = T[(p, m)]; w = t['w']; wd = len(wds)
    # 冲压：换模、压机线日报
    lines = S['st_lines']
    rows_dc, rows_pr = [], []
    for l in lines:
        if A_story:
            cnt, avg, die, spm, q = S['st_cnt'][l], S['st_smed'][l], S['st_die'][l], S['st_spm'][l], S['st_q'][l]
        else:
            cnt = int(round(S['st_cnt'][l] * wd / len(wds) * (0.9 + 0.2 * r.random()) * wd / 18))
            avg = round(S['st_smed'][l] * (1.12 - 0.12 * w) + r.uniform(-0.2, 0.2), 1)
            die = round(S['st_die'][l] + r.uniform(-0.4, 0.6), 1); spm = round(S['st_spm'][l] + r.uniform(-0.4, 0.5), 1); q = round(S['st_q'][l] + r.uniform(-0.05, 0.05), 1)
        tot = round(avg * cnt, 1)
        vals = alloc_float(tot, noisy_weights(r, cnt, 0.12), 1)
        for v in vals: rows_dc.append((eid('DC'), r.choice(wds).isoformat(), p, l, v))
        avail_tot = 900 * wd; run_tot = int(round(avail_tot * die / 100))
        design = 500 * wd * 10; act = int(round(design * spm / 100))
        parts_tot = 26000 * wd // 18 * 1  # 每线件数相同 → 加权=算术平均
        good = int(round(parts_tot * q / 100))
        av = alloc_int(avail_tot, [1] * wd); rn = alloc_int(run_tot, noisy_weights(r, wd, 0.03))
        ds = alloc_int(design, [1] * wd); ac = alloc_int(act, noisy_weights(r, wd, 0.03))
        pa = alloc_int(parts_tot, noisy_weights(r, wd, 0.05)); gd = alloc_int(good, pa)
        for i, d in enumerate(wds): rows_pr.append((d.isoformat(), p, l, av[i], rn[i], ds[i], ac[i], pa[i], gd[i]))
    ins(con, 'ods_mes_die_change', rows_dc); ins(con, 'ods_mes_press_daily', rows_pr)
    # 涂装烘房
    rows = []
    pt_shifts = sum(1 for _ in range(1)) and None
    for i, o in enumerate(S['pt_ovens']):
        code = f'{p}-PT-OV{i+1}'
        shifts_tot = t['shop']['PT']['shifts'] * wd
        idle_ps = S['pt_idle'][o] if A_story else round(S['pt_idle'][o] * (0.7 + 0.3 * w) + r.uniform(-2, 2))
        comp = S['pt_comp'][o] if A_story else min(99, round(S['pt_comp'][o] + (1 - w) * 7 + r.uniform(-1, 1)))
        idle_tot = int(round(idle_ps * shifts_tot))
        if A_story:
            shape = [max(5, x) for x in S['pt_idle_day'][:wd]]
        else:
            shape = noisy_weights(r, wd, 0.15)
        idle = alloc_int(idle_tot, shape)
        ss_tot = 50 if A_story else 2 * wd + 8
        compliant = int(round(comp / 100 * ss_tot))
        ss = alloc_int(ss_tot, [1] * wd); cp = alloc_int(compliant, ss)
        for k, d in enumerate(wds): rows.append((d.isoformat(), p, code, t['shop']['PT']['shifts'], idle[k], ss[k], min(cp[k], ss[k])))
    ins(con, 'ods_mes_oven_daily', rows)
    # 节拍
    rows = []
    for s, val in (('BD', S['bd_kpi']['takt'] if A_story else round(97.8 - 1.0 * w + r.uniform(-0.3, 0.3), 1)),
                   ('GA', S['gz']['takt'] if A_story else round(98.0 - 5.6 * w + r.uniform(-0.3, 0.3), 1))):
        design = 3600 / t['shop'][s]['tier_act']
        for d in wds:
            cyc = out_by_day.get((s, d), 0)
            rows.append((d.isoformat(), p, s, round(design, 2), round(design / (val / 100), 3), cyc))
    ins(con, 'ods_mes_takt_daily', rows)
    # Andon
    calls_tot = int(round((420 if A_story else 300 + 100 * w) * wd / 18))
    resp = S['gz']['andon'] if A_story else round(2.6 + 1.0 * w + r.uniform(-0.15, 0.15), 1)
    resp_tot = int(round(resp * 60 * calls_tot))
    calls = alloc_int(calls_tot, noisy_weights(r, wd, 0.2)); rsec = alloc_int(resp_tot, calls)
    ins(con, 'ods_mes_andon_daily', [(d.isoformat(), p, calls[k], rsec[k]) for k, d in enumerate(wds)])

def gen_quality(con, S, t, p, m, wds, out_by_day, r, A_story, defect_code, eid):
    wd = len(wds); q = t['q']; prod = t['prod']
    ga_out = [out_by_day.get(('GA', d), 0) for d in wds]
    rows = []
    for name, shopn, qty in q['defects']:
        sc = SHOP_CODE[shopn]
        if name == '色差/打磨印':
            if A_story:
                pd = dict((n, v) for n, v in S['pt_def']); split = [pd.get('色差', qty // 2), pd.get('打磨印', qty - qty // 2)]
                split[1] = qty - split[0]
            else:
                split = alloc_int(qty, [54, 46])
            items = [('色差', split[0]), ('打磨印', split[1])]
        else:
            items = [(name, qty)]
        for nm, v in items:
            code = defect_code[(nm, sc)]
            for k, x in enumerate(alloc_int(v, [g * (0.7 + 0.6 * r.random()) for g in ga_out])):
                if x: rows.append((eid('QD'), wds[k].isoformat(), p, sc, code, x))
    rows.append((eid('QD'), wds[-1].isoformat(), p, 'GA', 'D??', 3))   # 脏数据：未知缺陷代码
    ins(con, 'ods_qms_defect', rows)
    # 车间一次合格率
    rows = []
    for s in SHOPS:
        val = q['shop_ftt'][s]
        if s == 'ST': continue   # 冲压件合格率来自压机线日报
        insp = prod
        if s == 'GA':
            rw = ratio_count(q['rework'], insp); fp = insp - rw
        else:
            fp = ratio_count(val, insp); rw = insp - fp
        a = alloc_int(insp, ga_out); b = alloc_int(fp, a); c = [x - y for x, y in zip(a, b)]
        for k, d in enumerate(wds): rows.append((d.isoformat(), p, s, a[k], b[k], c[k]))
    ins(con, 'ods_qms_inspection', rows)
    fp = ratio_count(q['ftt'], prod)
    a = ga_out; b = alloc_int(fp, a)
    ins(con, 'ods_qms_vehicle_ftt', [(d.isoformat(), p, a[k], b[k]) for k, d in enumerate(wds)])
    cars = 60 if A_story else 40 + r.randint(0, 20)
    ins(con, 'ods_qms_audit', [(m, p, cars, round(q['audit'] * cars, 1))])
    vis, claims = denom_for_rate(q['warranty'] / 10, int(prod * 2.9), 1, 400)
    # warranty: claims/vis*1000 = q['warranty'] → 用 /10 的百分数复用 denom_for_rate
    ins(con, 'ods_qms_warranty', [(m, p, claims, vis)])
    reworkc = prod * q['rework'] / 100 * 380; scrap = prod * (6 + 4 * t['w']) * 1.0 * 12; war = claims * 2600; audit = 18000 + 12000 * t['w']
    ins(con, 'ods_qms_copq', [(m, p, '返修工时', round(reworkc, 2)), (m, p, '报废', round(scrap, 2)), (m, p, '保修索赔', round(war, 2)), (m, p, '复检/审核', round(audit, 2))])

def gen_logistics(con, S, t, p, m, wds, days, r, A_story, parts, story_parts, sup_rate, sup_batches, eid):
    wd = len(wds); w = t['w']
    rows = []
    for sup, rate0, b0 in S['suppliers']:
        if A_story:
            rate = rate0
            b, k = denom_for_rate(rate, b0, 1, 60)
        else:
            base = {'A': 1, 'B': 0.85, 'C': 0.7}[p]
            rate = round(min(99.5, _lerp(max(rate0, 93.5 + (rate0 - 76) * 0.15), rate0, w) + r.uniform(-0.6, 0.6)), 1)
            b = int(round(b0 * base * len(wds) / 18 * (0.9 + 0.2 * r.random())))
            k = ratio_count(rate, b)
        bb = alloc_int(b, noisy_weights(r, wd, 0.1)); kk = alloc_int(k, bb)
        for i, d in enumerate(wds): rows.append((eid('DL'), d.isoformat(), p, sup, bb[i], min(kk[i], bb[i])))
    rows.append(rows[0][:1] and (rows[0][0], rows[0][1], rows[0][2], rows[0][3], rows[0][4], rows[0][5]))   # 脏数据：重复批次记录
    ins(con, 'ods_wms_delivery', rows)
    # 线边缓冲快照（月末最后工作日；200 个关键零件）
    snap = wds[-1].isoformat()
    buckets = [(0.3, 0.95), (1.0, 1.95), (2.0, 3.95), (4.0, 7.9), (8.0, 24.0)]
    if A_story:
        counts = [c for _, c in S['lg_buckets']]
    else:
        low = int(round(_lerp(r.randint(4, 9), S['lg_low'], w)))
        counts = alloc_int(low, [6, 13, 18]) + alloc_int(200 - low, [41, 122])
    hours = {}
    for no, x in story_parts.items():
        if A_story or w > 0.5: hours[no] = x[6]
    rest = [q['no'] for q in parts if q['no'] not in hours]
    r.shuffle(rest)
    fixed_cnt = [0] * 5
    for no, h in hours.items():
        for bi, (lo, hi) in enumerate(buckets):
            if lo <= h <= hi + 0.05: fixed_cnt[bi] += 1; break
    rows = [(snap, p, no, h) for no, h in hours.items()]
    it = iter(rest)
    for bi, (lo, hi) in enumerate(buckets):
        for _ in range(max(0, counts[bi] - fixed_cnt[bi])):
            rows.append((snap, p, next(it), round(r.uniform(lo, hi), 1)))
    ins(con, 'ods_wms_lineside', rows)
    # 订单交付
    n0 = max(60, t['prod'] // 24)
    n, k = denom_for_rate(t['otd'], n0, 1, 80)
    late = set(r.sample(range(n), n - k))
    qty = alloc_int(t['prod'], noisy_weights(r, n, 0.3))
    lt_base = _lerp(18, 23.5, w)
    rows = []
    for i in range(n):
        ship = r.choice(wds)
        lt = max(7, int(round(r.gauss(lt_base, 3))))
        od = ship - dt.timedelta(days=lt)
        pr = ship + dt.timedelta(days=r.randint(0, 3)) if i not in late else ship - dt.timedelta(days=r.randint(1, 4))
        rows.append((f'SO-{p}{m.replace("-", "")}-{i:04d}', p, od.isoformat(), pr.isoformat(), ship.isoformat(), qty[i]))
    ins(con, 'ods_erp_order', rows)
    # 在制品 / 成品 / 外购件库存（日）
    dd = t['plan'] / wd
    rows = []
    for i, d in enumerate(wds):
        rows.append((d.isoformat(), p, 'WIP', int(round(dd * (0.62 + 0.25 * w) * (1 + r.uniform(-0.05, 0.05)))), round(dd, 2)))
        rows.append((d.isoformat(), p, 'FG', int(round(dd * (2.4 + 1.1 * w) * (1 + r.uniform(-0.08, 0.08)))), round(dd, 2)))
    # 外购件缓冲天数：日缓冲量 = 天数 × 日需求；月度加权严格等于目标
    shape = [1 + (0.25 * (1 - i / max(1, wd - 1)) - 0.12) * (w if p == 'A' else 0.2) for i in range(wd)]
    tot_units = t['buffer_days'] * dd * wd
    vals = alloc_int(tot_units, shape)
    for i, d in enumerate(wds): rows.append((d.isoformat(), p, 'PARTS', vals[i], round(dd, 2)))
    ins(con, 'ods_wms_inventory', rows)

def gen_energy(con, S, t, p, m, wds, out_by_day, r, A_story):
    wd = len(wds); prod = t['prod']
    price = {'peak': 1.10, 'flat': 0.70, 'valley': 0.35}
    rows = []
    totals = {}
    for s in SHOPS:
        e = t['en'][s]; d = t['shop'][s]
        fix_tot = e['fix'] * prod; ot_tot = e['ot_kwh']; var_tot = e['var'] * prod
        out = [out_by_day.get((s, x), 0) for x in wds]
        fx = alloc_float(fix_tot, [1 + r.uniform(-0.03, 0.03) for _ in wds], 1)
        ot = [round(d['run_kw'] * h, 1) for h in d['_ot_act_day']]; ot[-1] = round(ot[-1] + ot_tot - sum(ot), 1)
        if ot[-1]<0:
            # 把差额摊回前几天，避免负读数被质量规则剔除
            j=len(ot)-2
            while ot[-1]<0 and j>=0:
                take=min(ot[j], -ot[-1]); ot[j]=round(ot[j]-take,1); ot[-1]=round(ot[-1]+take,1); j-=1
        vr = alloc_float(var_tot, out, 1)
        if s == 'PT' and A_story:   # 涂装每日单车电耗形状取自示例（pt_e）
            pe = S['pt_e'][:wd]
            tot_d = [fx[i] + ot[i] + vr[i] for i in range(wd)]
            target_d = [pe[i] * out[i] for i in range(wd)]
            k = sum(tot_d) / sum(target_d)
            target_d = [x * k for x in target_d]
            # 用固定电量吸收差异（保持每日总量形状，总量不变）
            fx = [round(fx[i] + target_d[i] - tot_d[i], 1) for i in range(wd)]
            fx[-1] = round(fx[-1] + fix_tot - sum(fx), 1)
        tot_s = sum(fx) + sum(ot) + sum(vr)
        idle_tot = e['idle'] / 100 * tot_s
        idle = alloc_float(idle_tot, [fx[i] + ot[i] for i in range(wd)], 1)
        totals[s] = [fx, ot, vr, idle]
    # 峰平谷：工厂合计峰时占比 = 目标；各车间同比例（加班多集中在峰/平时段）
    peak = t['peak'] / 100; valley = 0.25 if A_story else round(0.27 - 0.02 * t['w'] + r.uniform(-0.01, 0.01), 3)
    grand = sum(sum(sum(x) for x in v[:3]) for v in totals.values())
    cost_target = sum(v for k, v in t['acc_act'].items() if k in S['GRP']['能源'])
    unit = peak * price['peak'] + (1 - peak - valley) * price['flat'] + valley * price['valley']
    k_cost = cost_target / (grand * unit)
    acc_cost = 0.0; acc_peak = 0.0
    for s in SHOPS:
        fx, ot, vr, idle = totals[s]
        for i, d in enumerate(wds):
            tot = fx[i] + ot[i] + vr[i]
            pk = round(tot * peak, 1); vl = round(tot * valley, 1); fl = round(tot - pk - vl, 1)
            cost = round((pk * price['peak'] + fl * price['flat'] + vl * price['valley']) * k_cost, 2)
            water = round(tot * {'ST': 0.002, 'BD': 0.003, 'PT': 0.012, 'GA': 0.004}[s], 2)
            rows.append([d.isoformat(), p, s, fx[i], ot[i], vr[i], idle[i], pk, fl, vl, cost, water])
            acc_cost += cost
    rows[-1][10] = round(rows[-1][10] + cost_target - acc_cost, 2)
    # 电量精确化：工厂单车电耗严格等于目标
    target_kwh = t['energy'] * prod
    cur_kwh = sum(x[3]+x[4]+x[5] for x in rows)
    dk = round(target_kwh - cur_kwh, 1)
    rows[-1][3] = round(rows[-1][3] + dk, 1)  # 调整最后一条固定电量
    # 峰时电量精确化
    tot_all = sum(x[3] + x[4] + x[5] for x in rows); pk_all = sum(x[7] for x in rows)
    dpk = round(tot_all * peak - pk_all, 1); rows[-1][7] = round(rows[-1][7] + dpk, 1); rows[-1][8] = round(rows[-1][8] - dpk, 1)
    ins(con, 'ods_ems_daily', [tuple(x) for x in rows])
    con.execute("INSERT INTO ods_ems_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (wds[0].isoformat(), p, 'ST', -120.0, 0, 0, 0, 0, 0, 0, 0, 0))  # 脏数据：负读数

def gen_hr(con, S, t, p, m, wds, r, A_story):
    wd = len(wds)
    rows = []
    for s in SHOPS:
        d = t['shop'][s]
        formal = d['head'] - d['disp'] - d['temp']
        rows += [(m, p, s, '正式', formal), (m, p, s, '派遣', d['disp']), (m, p, s, '临时', d['temp'])]
    ins(con, 'ods_hr_roster', rows)
    head = t['head']; sched_tot = head * wd
    present_tot = ratio_count(t['att'], sched_tot)
    if A_story: present_tot = S['hr_kpi']['att_n'] * wd
    att_shape = S['hr_w_att'] if A_story else None
    rows = []
    shop_present = alloc_int(present_tot, [t['shop'][s]['head'] * (0.985 if s == 'GA' and t['w'] > 0 else 1) for s in SHOPS])
    for si, s in enumerate(SHOPS):
        d = t['shop'][s]
        dayw = [1 - 0.04 * t['w'] * (i / max(1, wd - 1)) + r.uniform(-0.006, 0.006) for i in range(wd)]
        pres = alloc_int(shop_present[si], dayw)
        pres = [min(x, d['head']) for x in pres]
        pres[-1] += shop_present[si] - sum(pres)
        std = alloc_float(d['std_h'], [1] * wd, 1)
        ot = alloc_float(d['ot_h'], [max(0.01, x) for x in d['_ot_act_day']], 1)
        for i, day in enumerate(wds): rows.append((day.isoformat(), p, s, d['head'], pres[i], std[i], ot[i]))
    rows.append((wds[2].isoformat(), p, 'GA', 10, 12, 80.0, 0.0))  # 脏数据：出勤>排班
    ins(con, 'ods_hr_attendance', rows)

COST_CENTER_SPLIT = {'ST': 0.07, 'BD': 0.27, 'PT': 0.24, 'GA': 0.36, 'ADM': 0.06}
def gen_cost(con, S, t, p, m, r):
    rows = []
    for acc, amt in t['acc_act'].items():
        vals = alloc_float(amt, list(COST_CENTER_SPLIT.values()), 2)
        for cc, v in zip(COST_CENTER_SPLIT, vals): rows.append((m, p, cc, acc, v))
    ins(con, 'ods_erp_cost', rows)
    ins(con, 'ods_erp_spare', [(m, p, round((3.2e6 if p == 'A' else 2.6e6 if p == 'B' else 1.9e6) * (1 + 0.18 * t['w']) * (1 + r.uniform(-0.03, 0.03)), 2))])

def gen_maint_safety(con, S, t, p, m, wds, r, eid):
    w = t['w']
    eqs = con.execute('SELECT equip_code, shop_code FROM ods_md_equipment WHERE plant_code=? AND is_critical=1', (p,)).fetchall()
    rows = []
    pm_rate = _lerp(r.uniform(95, 98.5), 81.0, w) if p == 'A' else r.uniform(94, 98.5)
    for i, (eq, s) in enumerate(eqs):
        pd = wds[(i * 3) % len(wds)]
        done = r.random() < pm_rate / 100
        dd = (pd + dt.timedelta(days=r.randint(0, 2))).isoformat() if done else None
        rows.append((eid('WO'), p, s, eq, 'PM', pd.isoformat(), dd, r.randint(60, 240) if done else 0, None))
    # 纠正性维修：每个设备故障类停机事件对应一张 CM 工单
    fails = con.execute("SELECT event_id, biz_date, shop_code, equip_code, minutes FROM ods_mes_downtime WHERE plant_code=? AND substr(biz_date,1,7)=? AND reason IN ('设备故障','机器人故障','模具故障','输送链故障','喷涂机器人','烘房温控','夹具','输送','焊枪/电极')", (p, m)).fetchall()
    for ev, bd, s, eq, mm in fails:
        rows.append((eid('WO'), p, s, eq, 'CM', bd, bd, int(mm) if mm and mm > 0 else 0, ev))
    ins(con, 'ods_cmms_wo', rows)
    # 安全
    hrs = t['std_h'] + t['ot_h']
    rows = []
    n_lti = 1 if (p == 'A' and m in ('2026-09', '2026-10')) or (p == 'B' and m == '2026-03') or (p == 'C' and m == '2025-12') else 0
    for i in range(n_lti): rows.append((eid('IN'), r.choice(wds).isoformat(), p, r.choice(['GA', 'BD']), 'LTI', r.randint(3, 12)))
    for i in range(r.randint(1, 4)): rows.append((eid('IN'), r.choice(wds).isoformat(), p, r.choice(SHOPS), '急救', 0))
    for i in range(r.randint(3, 9)): rows.append((eid('IN'), r.choice(wds).isoformat(), p, r.choice(SHOPS), '未遂', 0))
    ins(con, 'ods_ehs_incident', rows)
    rows = []
    n_h = int(30 + 20 * w + r.randint(0, 10))
    close_rate = _lerp(r.uniform(0.9, 0.97), 0.78, w)
    for i in range(n_h):
        rd = r.choice(wds)
        closed = (rd + dt.timedelta(days=r.randint(1, 10))).isoformat() if r.random() < close_rate else None
        rows.append((eid('HZ'), p, r.choice(SHOPS), rd.isoformat(), closed, r.choice(['一般', '一般', '一般', '较大'])))
    ins(con, 'ods_ehs_hazard', rows)

def gen_buffers(con, S, t, p, m, wds, r, A_story):
    codes = {'冲压件库': 'STK', 'WBS 白车身库': 'WBS', 'PBS 涂装车身库': 'PBS'}
    f = t['prod'] / S['prod']['A工厂']
    rows, rows_p = [], []
    for name, (cap, eff, plan_end, act_end) in S['buffers'].items():
        c = codes[name]
        if not A_story:
            cap = int(round(cap * (f if p != 'A' else 1) / 10) * 10); eff = int(round(eff * (f if p != 'A' else 1) / 10) * 10)
            plan_end = int(round(plan_end * (f if p != 'A' else 1) * (0.9 + 0.2 * r.random())))
            act_end = int(round(plan_end * _lerp(1 + r.uniform(-0.1, 0.1), (act_end / plan_end if plan_end else 1.5), t['w']) if plan_end else (act_end * t['w'])))
            act_end = min(act_end, eff)
        rows_p.append(('VCS-BASE', m, p, c, cap, eff, plan_end))
        start = int(round(eff * 0.4))
        n = len(wds)
        for i, d in enumerate(wds):
            lvl = int(round(start + (act_end - start) * (i + 1) / n + r.uniform(-0.05, 0.05) * eff))
            lvl = max(0, min(eff, lvl))
            if i == n - 1: lvl = act_end
            rows.append((d.isoformat(), p, c, lvl))
    ins(con, 'ods_vcs_buffer_plan', rows_p); ins(con, 'ods_mes_buffer_daily', rows)

def gen_vcs_scenarios(con, S):
    rows = []
    for name, tot, unit in S['vcs_scen']:
        rows.append(('SEN-' + name, name, '敏感性', '年度转换成本', tot, '万元', '年度基准包（示例）'))
        rows.append(('SEN-' + name, name, '敏感性', '单车转换成本', unit, '元/台', ''))
    for name, v, u in S['vcs_limits']:
        rows.append(('LIM-' + name[:6], name, '预算安全边界', '可承受冲击', v, u, '不突破“基准+3%”预算前'))
    for name, v in S['vcs_strategy']:
        rows.append(('STR-' + name[:6], name, '策略溢价', '相对成本优先', v, '%' if '0.5（推荐）' not in name else '%', '稳定0.5：多约 116 万元，人数最大月波动 61%→19%' if '推荐' in name else ''))
    ins(con, 'ods_vcs_scenario', rows)

def gen_platform_logs(con, S):
    r = rng('platform')
    tasks = ['extract_mes', 'extract_erp', 'extract_wms', 'extract_qms', 'extract_ems', 'extract_hr', 'extract_vcs', 'dq_ods', 'build_dwd', 'build_dws', 'build_ads', 'refresh_bi']
    rows, dq, use = [], [], []
    roles = ['集团运营副总', '集团财务-成本控制经理', '工厂厂长', '工厂生产经理', '工厂计划经理', '车间主任', '工厂物流经理', '工厂质量经理', '工厂能源经理', '工厂人力资源经理']
    pages = ['集团总览', '工厂视图', '总装', '物流', '质量', '能源', '人力', 'VCS联动', '成本', '异常行动']
    users = [f'U{i:03d}' for i in range(1, 231)]
    i = 0
    for m in MONTHS:
        w = DEG.get(m, 0)
        for d in month_days(m):
            for tk in tasks:
                i += 1
                late = r.random() < (0.006 + (0.02 if tk == 'extract_mes' and w > 0.5 else 0))
                failed = r.random() < 0.002
                sla = f'{d.isoformat()} 06:00:00'
                end = f'{d.isoformat()} {"06:%02d" % r.randint(5, 50) if late else "05:%02d" % r.randint(0, 55)}:00'
                rows.append((f'JR{i:07d}', 'control_tower_daily', tk, d.isoformat(), sla, end, 'failed' if failed else 'success'))
            for rid, base in (('DQ01', 0.999), ('DQ02', 0.998), ('DQ03', 0.995), ('DQ04', 0.997), ('DQ05', 0.996), ('DQ06', 0.999), ('DQ07', 0.994), ('DQ08', 0.998)):
                n = r.randint(800, 4000); dq.append((d.isoformat(), rid, n, int(n * min(1, base + r.uniform(-0.004, 0.002)))))
            if is_workday(d):
                active = r.sample(users, int(120 + 60 * (MONTHS.index(m) / 11) + r.randint(-10, 10)))
                for u in active[: len(active) // 2]:
                    use.append((d.isoformat(), u, r.choice(roles), r.choice(pages), r.randint(1, 6)))
    ins(con, 'ods_sys_job_run', rows); ins(con, 'ods_sys_dq_history', dq); ins(con, 'ods_bi_usage', use)

from .targets import DEGRADE as DEG, _lerp

if __name__ == '__main__':
    import time; t0 = time.time(); generate(); print('done', round(time.time() - t0, 1), 's')
