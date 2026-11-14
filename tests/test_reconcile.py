"""对账：ADS / DWS 必须复现 data.py 故事月（2026-10）A工厂及集团的示例数字。"""
import math, pytest
from etl.common import connect, load_story, STORY_MONTH

@pytest.fixture(scope='module')
def con():
    c = connect()
    yield c
    c.close()

@pytest.fixture(scope='module')
def S():
    return load_story()

def ads(con, mid, plant=None, shop=None, month=STORY_MONTH):
    if shop:
        r = con.execute("SELECT * FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code=? AND shop_code=?",
                        (mid, month, plant, shop)).fetchone()
    elif plant:
        r = con.execute("SELECT * FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code=? AND shop_code IS NULL",
                        (mid, month, plant)).fetchone()
    else:
        r = con.execute("SELECT * FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code IS NULL",
                        (mid, month)).fetchone()
    assert r, f'missing {mid} plant={plant} shop={shop}'
    return r

def test_volume_and_cost(con, S):
    A = con.execute("SELECT * FROM dws_plant_month WHERE month=? AND plant_code='A'", (STORY_MONTH,)).fetchone()
    assert A['prod_qty'] == S['prod']['A工厂'] == 10340
    assert A['plan_qty'] == S['plan']['A工厂'] == 11000
    assert round(A['cost_total'] / A['prod_qty']) == S['cost']['A工厂'] == 5512
    assert round(A['cost_plan_total'] / A['plan_qty']) == S['cost_plan']['A工厂'] == 4997
    assert round(A['cost_total'] / 1e4, 1) == S['A_act_total'] == 5699.8
    assert round(A['cost_plan_total'] / 1e4, 1) == S['A_plan_total'] == 5497.0
    g = con.execute("SELECT * FROM dws_group_month WHERE month=?", (STORY_MONTH,)).fetchone()
    assert g['prod_qty'] == S['P']
    assert g['plan_qty'] == S['PP']
    assert round(g['cost_total'] / g['prod_qty']) == S['g_cost'] == 5202
    assert round(g['cost_plan_total'] / g['plan_qty']) == S['TGT_COST'] == 4980
    assert ads(con, 'unit_cost', 'A')['value'] == 5512
    assert ads(con, 'unit_cost')['value'] == 5202
    assert ads(con, 'ach_rate', 'A')['value'] == 94.0
    assert ads(con, 'ach_rate')['value'] == 96.9

def test_overtime_and_heads(con, S):
    A = con.execute("SELECT * FROM dws_plant_month WHERE month=? AND plant_code='A'", (STORY_MONTH,)).fetchone()
    assert int(A['ot_h']) == int(S['_tot_ot']) == 83284
    assert round(A['ot_h'] * 100 / A['std_h'], 1) == S['A_kpi']['ot'] == 29.5
    assert round(A['ot_h_plan'] * 100 / A['std_h'], 1) == S['A_kpi']['ot_plan'] == 25.1
    assert A['headcount'] == S['hr_kpi']['head'] == 1962
    assert ads(con, 'ot_rate', 'A')['value'] == 29.5
    assert ads(con, 'hpv', 'A')['value'] == pytest.approx(33.6, abs=0.05)
    assert ads(con, 'lab_cost', 'A')['value'] == 3241
    assert ads(con, 'attend', 'A')['value'] == 93.4

def test_vcs_execution_and_modes(con, S):
    assert ads(con, 'vcs_exec', 'A')['value'] == 62
    for s, name in [('ST','冲压'),('BD','焊装'),('PT','涂装'),('GA','总装')]:
        r = con.execute("SELECT * FROM dws_shop_month WHERE month=? AND plant_code='A' AND shop_code=?", (STORY_MONTH, s)).fetchone()
        assert r['tier_plan'] == S['vcs_mode'][name][0]
        assert r['shifts'] == S['vcs_mode'][name][1]
        assert abs(r['ot_line_h_act'] - S['ot_line_act'][name]) < 0.15
        assert abs(r['ot_line_h_plan'] - S['ot_line_plan'][name]) < 0.15
        assert ads(con, 'vcs_exec', 'A', s)['value'] == S['vcs_exec'][name]
        assert r['oee'] == S['shop_oee'][name]
        assert r['jph_rate'] == S['shop_jph'][name]
    assert ads(con, 'oee', 'A')['value'] == pytest.approx(81.2, abs=0.05)

def test_energy(con, S):
    assert ads(con, 'elec_kwh', 'A')['value'] == 494
    assert ads(con, 'elec_kwh')['value'] == 478
    assert ads(con, 'en_cost', 'A')['value'] == 378
    assert ads(con, 'paint_kwh', 'A', 'PT')['value'] == 270
    assert ads(con, 'peak_share', 'A')['value'] == 38

def test_assembly_stops_and_parts(con, S):
    assert ads(con, 'ga_stop', 'A', 'GA')['value'] == pytest.approx(43.7, abs=0.05)
    short = ads(con, 'short_cnt', 'A', 'GA')
    assert short['numerator'] == 86
    assert short['value'] == pytest.approx(1.76, abs=0.02)
    n, m = con.execute("""SELECT COUNT(*), SUM(minutes) FROM dwd_fact_downtime
                          WHERE plant_code='A' AND month=? AND shop_code='GA' AND reason='缺件'""", (STORY_MONTH,)).fetchone()
    assert n == 86 and m == 1155
    r = con.execute("""SELECT COUNT(*) c, SUM(minutes) m FROM dwd_fact_downtime
                       WHERE plant_code='A' AND month=? AND part_no='P-30117'""", (STORY_MONTH,)).fetchone()
    assert r['c'] == 14 and r['m'] == 196
    s07 = con.execute("""SELECT SUM(ontime_batches)*100.0/SUM(batches) r FROM dwd_fact_delivery
                         WHERE plant_code='A' AND month=? AND supplier_code='S07'""", (STORY_MONTH,)).fetchone()['r']
    assert round(s07, 1) == 76.5

def test_buffers_and_backlog(con, S):
    assert ads(con, 'backlog', 'A')['value'] == 660
    pbs = con.execute("""SELECT level_units FROM dwd_fact_buffer
                         WHERE plant_code='A' AND month=? AND buffer_code='PBS'
                         ORDER BY biz_date DESC LIMIT 1""", (STORY_MONTH,)).fetchone()['level_units']
    assert pbs == 500

def test_quality(con, S):
    assert ads(con, 'ftt', 'A')['value'] == 89.6
    assert ads(con, 'dpu', 'A')['value'] == pytest.approx(0.62, abs=0.005)
    assert ads(con, 'audit', 'A')['value'] == pytest.approx(1.8, abs=0.05)

def test_robot_and_shift_util(con, S):
    assert ads(con, 'robot_down', 'A', 'BD')['value'] == pytest.approx(18.0, abs=0.15)
    assert ads(con, 'shift_util', 'A')['value'] == pytest.approx(86.4, abs=0.15)
