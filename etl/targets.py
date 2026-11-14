"""目标模型（对账锚点）：把看板示例数据 config/story_targets.json（由 tools/sync_story.py 从 data.py 同步）
展开为 3 工厂 × 12 个月 × 4 车间 的月度锚点。
- 2026-10（故事月）A/B/C 工厂与集团值严格取自示例数据 → ETL 重算后必须复现（tests/test_reconcile.py）；
- 其余月份按“前 9 个月平稳、2026-07 起 A工厂恶化”的故事线确定性生成；
- VCS 参数（JPH 档、班次、班组人数、运行功率、线体加班、17 个成本科目、缓存）为一等公民。
所有数值均为示例数据。
"""
import datetime as dt
from .common import *

DEGRADE = {'2026-07': 0.12, '2026-08': 0.35, '2026-09': 0.65, '2026-10': 1.0}
VOL = {'A': 1.0}

def _lerp(a, b, w): return a + (b - a) * w

def story_workdays(S):
    y = int(S['MONTH'][:4])
    return [dt.date(y, int(x[:2]), int(x[3:])) for x in S['pt_days'][:S.get('WORKDAYS', len(S['pt_days']))]]

def build_targets(S=None):
    S = S or load_story()
    sm = S['MONTH']; assert sm == STORY_MONTH
    set_workday_override(sm, story_workdays(S))
    cn = lambda s: SHOP_NAME[s]
    pn = PLANT_NAME
    accounts = list(S['acc_plan'].keys())
    A_prod, A_plan = S['prod']['A工厂'], S['plan']['A工厂']
    wd_oct = len(workdays(sm))
    fac = {p: S['prod'][pn[p]] / A_prod for p in PLANTS}           # 规模系数（按故事月产量）
    T = {}
    cost_trend = dict(zip(S['months'], S['cost_trend']))
    plan_trend = dict(zip(S['months'], S['cost_plan_trend']))
    hr_trend = dict(zip(S['months'], S['hr_cost_trend']))
    en_trend = dict(zip(S['months'], S['en_cost_trend']))
    dpu_trend = dict(zip(S['months'], S['q_dpu_trend']))
    aud_trend = dict(zip(S['months'], S['q_audit_trend']))
    war_trend = dict(zip(S['months'], S['q_war_trend']))
    acc_act_A = {k: v * 1e4 for k, v in S['acc_act'].items()}
    acc_plan_A = {k: v * 1e4 for k, v in S['acc_plan'].items()}
    for m in MONTHS:
        wd = len(workdays(m))
        for p in PLANTS:
            r = rng('tgt', p, m); n = pn[p]
            w = DEGRADE.get(m, 0.0) if p == 'A' else 0.0
            t = {'w': w, 'wd': wd, 'story': (m == sm)}
            if m == sm:
                t.update(prod=S['prod'][n], plan=S['plan'][n], otd=S['otd'][n], oee=S['oee'][n])
                t['ot_ratio'] = S['otr'][n]; t['ot_plan_ratio'] = S['ot_plan'][n]
                t['energy'] = S['energy'][n]; t['energy_plan'] = S['energy_plan'][n]
            else:
                dd = S['plan'][n] / wd_oct * (1 + r.uniform(-0.035, 0.035))
                t['plan'] = int(round(dd * wd / 10) * 10)
                ach = {'A': _lerp(99.1, 94.0, w), 'B': 98.9, 'C': 99.2}[p] + r.uniform(-0.4, 0.3)
                t['prod'] = int(round(t['plan'] * ach / 100))
                t['otd'] = round({'A': _lerp(97.2, S['otd'][n], w), 'B': S['otd']['B工厂'], 'C': S['otd']['C工厂']}[p] + r.uniform(-0.5, 0.4), 1)
                t['oee'] = round({'A': _lerp(85.8, S['oee'][n], w), 'B': S['oee']['B工厂'], 'C': S['oee']['C工厂']}[p] + r.uniform(-0.5, 0.5), 1)
                t['ot_plan_ratio'] = round(S['ot_plan'][n] * (dd / (S['plan'][n] / wd_oct)) ** 2, 1)
                t['ot_ratio'] = round(t['ot_plan_ratio'] * _lerp(1 + r.uniform(-0.03, 0.03), S['otr'][n] / S['ot_plan'][n], w if p == 'A' else 0), 1)
                t['energy_plan'] = S['energy_plan'][n] + r.choice([-2, -1, 0, 1, 2])
                t['energy'] = round(t['energy_plan'] * _lerp(1.0 + r.uniform(-0.006, 0.012), S['energy'][n] / S['energy_plan'][n], w if p == 'A' else 0.4))
            T[(p, m)] = t
        # ---------- 单车转换成本（实际 & VCS 测算），集团加权严格等于趋势 ----------
        if m == sm:
            for p in PLANTS:
                T[(p, m)]['cost_total'] = S['cost'][pn[p]] * T[(p, m)]['prod']
                T[(p, m)]['plan_cost_total'] = S['cost_plan'][pn[p]] * T[(p, m)]['plan']
        else:
            w = DEGRADE.get(m, 0)
            Pp = sum(T[(p, m)]['prod'] for p in PLANTS); PPl = sum(T[(p, m)]['plan'] for p in PLANTS)
            g = cost_trend[m]; gp = plan_trend[m]
            offA = _lerp(150, S['cost']['A工厂'] - S['g_cost'], w); offB = -80
            a = round((g + offA) * T[('A', m)]['prod']); b = round((g + offB) * T[('B', m)]['prod'])
            T[('A', m)]['cost_total'] = a; T[('B', m)]['cost_total'] = b; T[('C', m)]['cost_total'] = round(g * Pp) - a - b
            a = round((gp + 17) * T[('A', m)]['plan']); b = round(gp * T[('B', m)]['plan'])
            T[('A', m)]['plan_cost_total'] = a; T[('B', m)]['plan_cost_total'] = b; T[('C', m)]['plan_cost_total'] = round(gp * PPl) - a - b
        # ---------- 17 个 VCS 科目拆分 ----------
        for p in PLANTS:
            t = T[(p, m)]
            if p == 'A' and m == sm:
                t['acc_act'] = dict(acc_act_A); t['acc_plan'] = dict(acc_plan_A)
                continue
            # 实际：人工类按 hr 趋势、能源按能源趋势（A），其余按 A 故事月结构
            lab_keys = S['GRP']['人工（含间接/夜班/福利）'] + S['GRP']['加班（含超限溢价）']
            en_keys = S['GRP']['能源']
            def split(total, base, prod, lab_u=None, en_u=None):
                out = {}
                lab_tot = sum(base[k] for k in lab_keys); en_tot = sum(base[k] for k in en_keys)
                rest_keys = [k for k in accounts if k not in lab_keys and k not in en_keys]
                rest_tot = sum(base[k] for k in rest_keys)
                L = lab_u * prod if lab_u else total * lab_tot / sum(base.values())
                E = en_u * prod if en_u else total * en_tot / sum(base.values())
                R = total - L - E
                for k in lab_keys: out[k] = L * base[k] / lab_tot
                for k in en_keys: out[k] = E * base[k] / en_tot
                for k in rest_keys: out[k] = R * base[k] / rest_tot if rest_tot else 0
                return {k: round(out[k], 2) for k in accounts}
            base_act = dict(acc_act_A)
            if m != sm:   # 正常月：加班 / 延期成本按计划结构
                base_act = dict(acc_plan_A); base_act['延期成本'] = acc_plan_A['延期成本']
            if p == 'A':
                t['acc_act'] = split(t['cost_total'], base_act, t['prod'], hr_trend[m], en_trend[m])
            else:
                t['acc_act'] = split(t['cost_total'], base_act, t['prod'])
            t['acc_plan'] = split(t['plan_cost_total'], acc_plan_A, t['plan'])
            # 修正舍入：让合计严格等于总额
            for key, tot in (('acc_act', t['cost_total']), ('acc_plan', t['plan_cost_total'])):
                d = round(tot - sum(t[key].values()), 2)
                t[key]['OH变动'] = round(t[key]['OH变动'] + d, 2)
    # ---------- 车间级 ----------
    norm_oee_off = {'ST': 2.0, 'BD': 0.6, 'PT': -0.2, 'GA': -2.4}
    oct_oee_off = {SHOP_CODE[k]: v - S['A_kpi']['oee'] for k, v in S['shop_oee'].items()}
    oct_jph_off = {SHOP_CODE[k]: v - S['shop_jph']['总装'] for k, v in S['shop_jph'].items()}
    norm_jph_off = {'ST': 1.0, 'BD': 0.6, 'PT': 0.4, 'GA': 0.0}
    stop_A = {'ST': [tuple(x) for x in S['st_stop']], 'BD': [tuple(x) for x in S['bd_stop']],
              'PT': [('输送链故障', 260), ('喷涂机器人', 210), ('换色/清洗', 180), ('烘房温控', 150), ('其他', 90)],
              'GA': [tuple(x) for x in S['stop_reason']]}
    for (p, m), t in T.items():
        w = t['w']; r = rng('shop', p, m); wd = t['wd']; A_story = (p == 'A' and m == sm); f = fac[p]
        t['jph'] = S['A_kpi']['jph'] if A_story else round({'A': _lerp(98.6, S['A_kpi']['jph'], w), 'B': 98.3, 'C': 98.7}[p] + r.uniform(-0.4, 0.3), 1)
        t['shift_util'] = S['A_kpi']['shift_util'] if A_story else round({'A': _lerp(92.1, S['A_kpi']['shift_util'], w), 'B': 91.4, 'C': 92.6}[p] + r.uniform(-0.6, 0.6), 1)
        t['buffer_days'] = S['A_kpi']['buffer'] if A_story else round({'A': _lerp(2.1, S['A_kpi']['buffer'], w), 'B': 1.9, 'C': 2.0}[p] + r.uniform(-0.1, 0.1), 1)
        oee_off = {s: _lerp(norm_oee_off[s], oct_oee_off[s], w) for s in SHOPS}
        mo = sum(oee_off.values()) / 4
        shop = {}
        dd_ratio = (t['plan'] / wd) / (S['plan'][PLANT_NAME[p]] / wd_oct)
        for s in SHOPS:
            d = {}
            c = cn(s)
            if A_story:
                d['oee'] = S['shop_oee'][c]; d['jph'] = S['shop_jph'][c]
            else:
                d['oee'] = round(t['oee'] + oee_off[s] - mo, 1)
                d['jph'] = t['jph'] if s == 'GA' else round(min(99.6, t['jph'] + _lerp(norm_jph_off[s], oct_jph_off[s], w)), 1)
            # VCS：档位 / 班次 / 班组
            tiers = S['VCS_TIERS'][c]
            d['tiers'] = tiers
            mode_jph, mode_sh = S['vcs_mode'][c]
            if p != 'A':   # 规模较小工厂选低一档
                mode_jph = max([x for x in tiers if x <= mode_jph * max(f, 0.62) / 0.83] or [tiers[0]])
            d['tier_plan'] = mode_jph; d['tier_act'] = mode_jph; d['shifts'] = mode_sh
            ratio = mode_jph / S['vcs_mode'][c][0]
            d['heads_shift'] = int(round(S['heads_shift'][c] * ratio)); d['ind_shift'] = int(round(S['ind_shift'][c] * (0.5 + 0.5 * ratio)))
            d['crew'] = d['heads_shift'] + d['ind_shift']
            d['head'] = d['crew'] * mode_sh
            d['run_kw'] = int(round(S['run_kw'][c] * (0.6 + 0.4 * ratio)))
            disp, tmp = S['hr_temp'][c]
            d['disp'] = disp if A_story else int(round(disp * d['head'] / S['hr_head'][c] * (0.8 + 0.2 * w if p == 'A' else 0.85)))
            d['temp'] = tmp if A_story else int(round(tmp * d['head'] / S['hr_head'][c] * (0.8 + 0.2 * w if p == 'A' else 0.85)))
            if A_story:
                d['ot_line_plan'] = S['ot_line_plan'][c]; d['ot_line_act'] = S['ot_line_act'][c]
            else:
                base = S['ot_line_plan'][c] * (S['plan'][PLANT_NAME[p]] / wd_oct / (mode_jph * mode_sh * 7.5)) / (A_plan / wd_oct / (S['vcs_mode'][c][0] * 2 * 7.5))
                d['ot_line_plan'] = round(max(4.0, base * wd / wd_oct * dd_ratio ** 3), 1)
                d['ot_line_act'] = round(d['ot_line_plan'] * _lerp(1 + r.uniform(-0.04, 0.05), S['ot_line_act'][c] / S['ot_line_plan'][c], w), 1)
            shop[s] = d
        if not A_story:
            diff = round(t['oee'] * 4 - sum(shop[s]['oee'] for s in SHOPS), 1)
            shop['GA']['oee'] = round(shop['GA']['oee'] + diff, 1)
        # 加班人·h 与加班率：非故事月按目标加班率反推线体加班（逐车间等比缩放）
        std_tot = sum(shop[s]['head'] * wd * 8 for s in SHOPS)
        if not (m == sm):
            for key, ratio_key in (('ot_line_act', 'ot_ratio'), ('ot_line_plan', 'ot_plan_ratio')):
                cur = sum(shop[s][key] * shop[s]['crew'] for s in SHOPS) / std_tot * 100
                k = t[ratio_key] / cur
                for s in SHOPS: shop[s][key] = round(shop[s][key] * k, 1)
        elif p != 'A':
            for key, ratio_key in (('ot_line_act', 'ot_ratio'), ('ot_line_plan', 'ot_plan_ratio')):
                # B/C 故事月：按 A 的车间结构缩放到目标加班率
                for s in SHOPS: shop[s][key] = S[key][cn(s)]
                cur = sum(shop[s][key] * shop[s]['crew'] for s in SHOPS) / std_tot * 100
                k = t[ratio_key] / cur
                for s in SHOPS: shop[s][key] = round(shop[s][key] * k, 1)
        # 精确化：调整总装线体加班使加班率四舍五入后严格等于目标
        for key, ratio_key in (('ot_line_act', 'ot_ratio'), ('ot_line_plan', 'ot_plan_ratio')):
            if A_story: break
            for _ in range(400):
                tot = sum(round(shop[s][key] * shop[s]['crew']) for s in SHOPS)
                val = round(tot / std_tot * 100, 1)
                if val == t[ratio_key]: break
                shop['GA'][key] = round(shop['GA'][key] + (0.1 if val < t[ratio_key] else -0.1), 1)
        for s in SHOPS:
            d = shop[s]
            d['std_h'] = d['head'] * wd * 8
            d['ot_h'] = int(round(d['ot_line_act'] * d['crew'])); d['ot_h_plan'] = int(round(d['ot_line_plan'] * d['crew']))
            # VCS 执行：一致车间天数
            if A_story:
                d['exec_days'] = ratio_count(S['vcs_exec'][cn(s)], wd) if False else round(S['vcs_exec'][cn(s)] / 100 * wd)
            else:
                rate = _lerp(r.uniform(86, 95), S['vcs_exec'][cn(s)], w)
                d['exec_days'] = int(round(rate / 100 * wd))
            # 停线 / 停机分钟（按原因）
            if A_story:
                d['stops'] = stop_A[s]
            else:
                per = {'ST': 16, 'BD': 30, 'PT': 22, 'GA': 30}[s] * _lerp(1, 1.25, w)
                tot_min = per * (2 * wd) * (0.9 + 0.2 * r.random())
                names = [x[0] for x in stop_A[s]]
                base = [x[1] for x in stop_A[s]]
                if s == 'GA':   # 正常月缺件占比低
                    base = [base[0] * _lerp(0.35, 1, w)] + base[1:]
                vals = alloc_int(tot_min, [b * (0.8 + 0.4 * r.random()) for b in base])
                d['stops'] = list(zip(names, vals))
        t['shop'] = shop
        t['std_h'] = sum(shop[s]['std_h'] for s in SHOPS)
        t['ot_h'] = sum(shop[s]['ot_h'] for s in SHOPS)
        t['head'] = sum(shop[s]['head'] for s in SHOPS)
        t['att'] = S['hr_kpi']['att'] if A_story else round({'A': _lerp(96.9, S['hr_kpi']['att'], w), 'B': 96.6, 'C': 97.1}[p] + r.uniform(-0.3, 0.3), 1)
        # 能源（电，VCS 口径）：固定=功率×开动；加班=功率×加班；变动=单车电耗×产量
        en = {}
        for s in SHOPS:
            c = cn(s)
            if A_story:
                en[s] = dict(fix=S['el_fix'][c], var=S['el_var'][c], ot_kwh=S['run_kw'][c] * shop[s]['ot_line_act'],
                             idle=S['en_idle_shop'][c], plan=S['el_plan_shop'][c])
            else:
                en[s] = dict(fix=S['el_fix'][c] * (S['prod']['A工厂'] / wd_oct) / (t['prod'] / wd) * shop[s]['run_kw'] / S['run_kw'][c],
                             var=S['el_var'][c], ot_kwh=shop[s]['run_kw'] * shop[s]['ot_line_act'],
                             idle=round(_lerp(S['en_idle_shop'][c] * 0.62, S['en_idle_shop'][c], w if p == 'A' else 0.25), 1),
                             plan=S['el_plan_shop'][c])
        if not A_story:   # 缩放固定电量使工厂单车电耗 = 目标
            for _ in range(3):
                cur = sum(en[s]['fix'] + en[s]['var'] + en[s]['ot_kwh'] / t['prod'] for s in SHOPS)
                k = (t['energy'] - sum(en[s]['var'] + en[s]['ot_kwh'] / t['prod'] for s in SHOPS)) / sum(en[s]['fix'] for s in SHOPS)
                for s in SHOPS: en[s]['fix'] = round(en[s]['fix'] * k, 1)
        t['en'] = en
        t['peak'] = S['en_kpi']['peak'] if A_story else round({'A': _lerp(31, S['en_kpi']['peak'], w), 'B': 31.5, 'C': 30.5}[p] + r.uniform(-1, 1))
        # 质量
        if A_story:
            t['q'] = dict(ftt=S['q_kpi']['ftt'], audit=S['q_kpi']['audit'], warranty=S['q_kpi']['warranty'], rework=S['q_kpi']['rework'],
                          defects=[tuple(x) for x in S['q_def']], shop_ftt={SHOP_CODE[k]: v[0] for k, v in S['q_shop_ftt'].items()})
        else:
            dpu = dpu_trend[m] if p == 'A' else {'B': 0.47, 'C': 0.44}[p] + r.uniform(-0.02, 0.02)
            scale = dpu / S['q_kpi']['dpu']
            defs = []
            for name, shopn, v in S['q_def']:
                k = scale * (_lerp(0.55, 1, w) if name in ('缺件补装', '线束插接不良') else 1.08)
                defs.append((name, shopn, int(round(v / S['prod']['A工厂'] * t['prod'] * k * (0.92 + 0.16 * r.random())))))
            t['q'] = dict(ftt=round(_lerp(92.6, S['q_kpi']['ftt'], w) + r.uniform(-0.3, 0.3), 1), audit=aud_trend[m] if p == 'A' else round(1.3 + r.uniform(-0.1, 0.1), 1),
                          warranty=war_trend[m] if p == 'A' else round(11.0 + r.uniform(-0.6, 0.6), 1), rework=round(_lerp(4.3, S['q_kpi']['rework'], w) + r.uniform(-0.2, 0.2), 1),
                          defects=defs, shop_ftt={'ST': round(99.3 + r.uniform(-0.1, 0.1), 1), 'BD': round(95.8 + r.uniform(-0.3, 0.3), 1),
                                                  'PT': round(91.3 + r.uniform(-0.4, 0.4), 1), 'GA': None})
            t['q']['shop_ftt']['GA'] = round(100 - t['q']['rework'], 1)
    return T

if __name__ == '__main__':
    T = build_targets()
    for m in MONTHS:
        print(m, {p: (T[(p, m)]['prod'], T[(p, m)]['plan'], round(T[(p, m)]['cost_total'] / T[(p, m)]['prod']), T[(p, m)]['ot_ratio'], T[(p, m)]['energy']) for p in PLANTS})
    t = T[('A', '2026-10')]
    for s in SHOPS: print(s, {k: v for k, v in t['shop'][s].items() if k != 'stops'})
