"""公共工具：路径、数据库连接、日历、确定性随机与整数分配。仅依赖 Python 标准库。"""
import os, json, sqlite3, random, datetime as dt, math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get('CT_DB', os.path.join(ROOT, 'data', 'control_tower.db'))
CONFIG = os.path.join(ROOT, 'config')
SEED = 20261031

PLANTS = ['A', 'B', 'C']
PLANT_NAME = {'A': 'A工厂', 'B': 'B工厂', 'C': 'C工厂'}
SHOPS = ['ST', 'BD', 'PT', 'GA']
SHOP_NAME = {'ST': '冲压', 'BD': '焊装', 'PT': '涂装', 'GA': '总装'}
SHOP_CODE = {v: k for k, v in SHOP_NAME.items()}
AREAS = SHOPS + ['UT']                      # 能源分区：四车间 + 公用动力
AREA_NAME = dict(SHOP_NAME, UT='公用动力')
SLOTS = ['S1', 'S2', 'S3']                   # 早/中/夜
SLOT_NAME = {'S1': '早班', 'S2': '中班', 'S3': '夜班'}
MONTHS = ['2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-04',
          '2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10']
STORY_MONTH = '2026-10'

def connect(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con

def load_story():
    return json.load(open(os.path.join(CONFIG, 'story_targets.json'), encoding='utf-8'))

def rng(*keys):
    """按业务键派生的确定性随机数发生器：同一键永远得到同一序列。"""
    return random.Random(f'{SEED}|' + '|'.join(map(str, keys)))

# ---------------- 日历（示例：近似中国法定节假日与调休） ----------------
HOLIDAYS = set()
def _rng_days(a, b):
    d = dt.date.fromisoformat(a)
    while d <= dt.date.fromisoformat(b):
        yield d; d += dt.timedelta(days=1)
for a, b in [('2026-01-01', '2026-01-03'), ('2026-02-15', '2026-02-23'), ('2026-04-04', '2026-04-06'),
             ('2026-05-01', '2026-05-05'), ('2026-06-19', '2026-06-21'), ('2026-09-25', '2026-09-27'),
             ('2026-10-01', '2026-10-07')]:
    HOLIDAYS.update(_rng_days(a, b))
MAKEUP = {dt.date.fromisoformat(x) for x in ['2026-01-04', '2026-02-14', '2026-02-28', '2026-05-09',
                                              '2026-10-10', '2026-10-11']}
# 2026-10：10/08、10/09 节后复工为工作日（与看板“涂装每日能耗”的 19 个工作日一致）

def month_days(m):
    y, mo = map(int, m.split('-'))
    d = dt.date(y, mo, 1)
    while d.month == mo:
        yield d; d += dt.timedelta(days=1)

def is_workday(d):
    m = d.strftime('%Y-%m')
    if m in _WD_OVERRIDE: return d in _WD_OVERRIDE[m]
    if d in MAKEUP: return True
    if d in HOLIDAYS: return False
    return d.weekday() < 5

_WD_OVERRIDE = {}
def set_workday_override(month, days):
    """故事月的工作日以示例数据为准（data.py: pt_days[:WORKDAYS]）。"""
    _WD_OVERRIDE[month] = sorted(days)

def workdays(m):
    if m in _WD_OVERRIDE:
        return list(_WD_OVERRIDE[m])
    return [d for d in month_days(m) if is_workday(d)]

def iso_week(d):
    return 'W%02d' % d.isocalendar()[1]

# ---------------- 整数分配 ----------------
def alloc_int(total, weights):
    """最大余数法把整数 total 按权重分配，保证和严格等于 total。"""
    total = int(round(total))
    s = float(sum(weights))
    if s <= 0:
        weights = [1] * len(weights); s = len(weights)
    raw = [total * w / s for w in weights]
    base = [math.floor(x) for x in raw]
    rem = total - sum(base)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in order[:rem]:
        base[i] += 1
    return base

def alloc_float(total, weights, nd=2):
    s = float(sum(weights)) or 1.0
    vals = [round(total * w / s, nd) for w in weights]
    vals[-1] = round(total - sum(vals[:-1]), nd)
    return vals

def noisy_weights(r, n, cv=0.15):
    return [max(0.05, r.gauss(1, cv)) for _ in range(n)]

def ratio_count(rate_pct, denom):
    """返回整数分子，使 分子/denom 四舍五入到 1 位小数后等于 rate_pct（找不到则最近）。"""
    k = round(rate_pct / 100 * denom)
    for c in [k, k - 1, k + 1, k - 2, k + 2]:
        if 0 <= c <= denom and round(c / denom * 100, 1) == round(rate_pct, 1):
            return c
    return max(0, min(denom, k))

def denom_for_rate(rate_pct, approx, nd=1, span=40):
    """在 approx 附近找一个分母，使存在整数分子精确复现 rate_pct（nd 位小数）。"""
    for delta in range(0, span):
        for d in (approx + delta, approx - delta):
            if d <= 0: continue
            k = round(rate_pct / 100 * d)
            if round(k / d * 100, nd) == round(rate_pct, nd):
                return d, k
    k = round(rate_pct / 100 * approx)
    return approx, k
