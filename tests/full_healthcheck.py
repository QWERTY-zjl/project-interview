# -*- coding: utf-8 -*-
"""
项目全面体检脚本：鉴权 / 配额 / 已删接口 / 边界行为
==================================================
按依赖顺序检查（任何一步 FAIL 不影响后续独立检查项）：
  A. 服务器存活 + 数据库读写可用（锁状态）
  B. 已删老接口确认 404（匿名开面试的后门已封）
  C. 未登录访问受保护接口一律 401
  D. 完整用户链路：注册→登录→查配额→配额0被拦→配额恢复放行→登出→旧token失效
  E. 边界：面试详情接口（公开token查询）、表情接口空图、AI辅助假token
"""
import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config.config import DATABASE_NAME

BASE = 'http://127.0.0.1:10009'
STAMP = str(int(time.time()))
USERNAME = f'healthcheck_{STAMP}'
RESULTS = []


def record(name, ok, detail=''):
    RESULTS.append((name, ok, detail))


def http(method, path, data=None, headers=None, timeout=10, is_json=False):
    """HTTP 请求 → (status|'timeout'|'conn-refused', dict|bytes)。is_json=True 自动带 JSON 头"""
    if is_json:
        headers = {'Content-Type': 'application/json', **(headers or {})}
    req = urllib.request.Request(BASE + path, data=data, headers=headers or {}, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        body = r.read().decode('utf-8', 'replace')
        try:
            return r.status, json.loads(body)
        except Exception:
            return r.status, body[:60]
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body[:60]
    except TimeoutError:
        return 'timeout', {}
    except Exception:
        return 'conn-refused', {}


def json_body(obj):
    return json.dumps(obj).encode('utf-8')


# ---------- A. 服务器 + 数据库 ----------
code, _ = http('GET', '/')
record('A1 服务器存活', code == 200, f'GET / -> {code}')

try:
    conn = sqlite3.connect(DATABASE_NAME, timeout=3)
    conn.execute("CREATE TABLE IF NOT EXISTS _healthcheck(t TEXT)")
    conn.execute("INSERT INTO _healthcheck VALUES('x')")
    conn.commit()
    conn.execute("DROP TABLE _healthcheck")
    conn.commit()
    conn.close()
    record('A2 数据库可写（无长期锁）', True)
except sqlite3.OperationalError as e:
    record('A2 数据库可写（无长期锁）', False, f'{e} —— 有流程长期持锁，需重启服务器')

# ---------- B. 已删接口 ----------
for path in ('/api/interview/create', '/api/interview/create_and_redirect'):
    code, _ = http('POST', path, json_body({}), {'Content-Type': 'application/json'})
    record(f'B 已删接口 404: {path}', code == 404, f'-> {code}')

# ---------- C. 未登录 401 ----------
for method, path, data in [
    ('GET', '/api/interview/my_records', None),
    ('GET', '/api/user/quota', None),
]:
    code, _ = http(method, path)
    record(f'C 未登录 401: {path}', code == 401, f'-> {code}')

# 上传接口的鉴权在函数体内（参数校验之后），要用合法 multipart 才能测到 401
cleanform = ('--B\r\nContent-Disposition: form-data; name="work_experience"\r\n\r\n1年\r\n'
             '--B\r\nContent-Disposition: form-data; name="target_position"\r\n\r\n测试岗\r\n'
             '--B\r\nContent-Disposition: form-data; name="resume"; filename="a.pdf"\r\n'
             'Content-Type: application/pdf\r\n\r\n%PDF-1.4 t\r\n--B--\r\n').encode('utf-8')
code, _ = http('POST', '/api/resume/upload', cleanform,
               {'Content-Type': 'multipart/form-data; boundary=B'})
record('C 未登录 401: /api/resume/upload', code == 401, f'-> {code}')

# ---------- D. 完整用户链路 ----------
code, body = http('POST', '/api/auth/register', json_body({
    'username': USERNAME, 'email': USERNAME + '@test.com', 'password': 'test123456'}), is_json=True)
record('D1 注册', code in (200, 201), f'-> {code}')

db = sqlite3.connect(DATABASE_NAME, timeout=3)
db.row_factory = sqlite3.Row
row = db.execute('SELECT id, interview_quota FROM users WHERE username=?', (USERNAME,)).fetchone()
uid = row['id'] if row else None
record('D2 注册默认配额 3', bool(row) and row['interview_quota'] == 3,
       f'quota={row["interview_quota"] if row else "?"}')

code, body = http('POST', '/api/auth/login', json_body({
    'username': USERNAME, 'password': 'test123456'}), is_json=True)
TOKEN = body.get('auth_token') or (body.get('user') or {}).get('auth_token', '')
record('D3 登录', code == 200 and bool(TOKEN), f'-> {code}')
AUTH = {'Authorization': f'Bearer {TOKEN}'}

code, body = http('GET', '/api/user/quota', headers=AUTH)
q = (body.get('quota') or {}).get('total_available', {}).get('interviews')
record('D4 登录态查配额', code == 200 and q == 3, f'-> {code} interviews={q}')

code, body = http('GET', '/api/interview/my_records', headers=AUTH)
n = body.get('stats', {}).get('total_count', -1)
record('D5 新用户记录 0 场', code == 200 and n == 0, f'-> {code} total={n}')

# 配额 0：上传必须被拦
db.execute('UPDATE users SET interview_quota=0 WHERE id=?', (uid,))
db.commit()
form = ('--B\r\nContent-Disposition: form-data; name="work_experience"\r\n\r\n1年\r\n'
        '--B\r\nContent-Disposition: form-data; name="target_position"\r\n\r\n测试岗\r\n'
        '--B\r\nContent-Disposition: form-data; name="resume"; filename="a.pdf"\r\n'
        'Content-Type: application/pdf\r\n\r\n%PDF-1.4 t\r\n--B--\r\n').encode()
code, body = http('POST', '/api/resume/upload', form,
                  {'Content-Type': 'multipart/form-data; boundary=B', **AUTH})
record('D6 配额0上传被拦', code == 422, f'-> {code} {json.dumps(body, ensure_ascii=False)[:70]}')

# 配额 1：闸门放行（用无 %PDF 头文件触发 400 NOT_PDF，避免真调大模型）
db.execute('UPDATE users SET interview_quota=1 WHERE id=?', (uid,))
db.commit()
badform = form.replace(b'%PDF-1.4 t', b'not a pdf at all')
code, body = http('POST', '/api/resume/upload', badform,
                  {'Content-Type': 'multipart/form-data; boundary=B', **AUTH})
err = json.dumps(body, ensure_ascii=False)
record('D7 配额1放行到PDF校验', code == 400 and 'PDF' in err, f'-> {code} {err[:70]}')

# 空字符串工作经验直接绕过前端调接口：应仍能到达校验层（后端现状：空串可过，
# 这里记录现状供汇总），用假PDF触发400 NOT_PDF 证明没在分析层炸掉
emptyform = form.decode('utf-8').replace('\r\n\r\n1年\r\n', '\r\n\r\n\r\n').encode('utf-8')
code, body = http('POST', '/api/resume/upload', emptyform,
                  {'Content-Type': 'multipart/form-data; boundary=B', **AUTH})
record('D8 经验空串到达后端校验层', code in (400, 422), f'-> {code}（后端暂不拦空串，见汇总）')

# 登出后旧 token 失效
code, _ = http('POST', '/api/auth/logout', json_body({}), AUTH, is_json=True)
code2, _ = http('GET', '/api/user/quota', headers=AUTH)
record('D9 登出后旧token失效', code == 200 and code2 == 401, f'logout={code} 复用={code2}')
db.close()

# ---------- E. 边界 ----------
code, body = http('GET', '/api/interview/9BKcbKF9MAGhpAsSQldLzaRrwiYC87Cf/detail')
qs = len(body.get('questions') or []) if isinstance(body, dict) else 0
record('E1 面试详情接口(带报告)', code == 200 and qs > 0, f'-> {code} questions={qs}')

code, body = http('GET', '/api/interview/not_a_real_token/detail')
record('E2 假token详情 404', code == 404, f'-> {code}')

code, body = http('POST', '/api/expression/analyze', json_body({}), {'Content-Type': 'application/json'})
record('E3 表情接口空图 400', code == 400, f'-> {code}')

code, body = http('POST', f'/api/interview/{STAMP}fake/hint', json_body({'question_id': 1}),
                  {'Content-Type': 'application/json'})
record('E4 假token AI辅助被拒', code in (401, 404), f'-> {code}')

# ---------- 清理 + 汇总 ----------
try:
    db = sqlite3.connect(DATABASE_NAME, timeout=3)
    db.execute('DELETE FROM users WHERE username=?', (USERNAME,))
    db.commit()
    db.close()
    record('Z 清理测试用户', True, USERNAME)
except sqlite3.OperationalError as e:
    record('Z 清理测试用户', False, str(e))

print()
print('=' * 72)
fails = 0
for name, ok, detail in RESULTS:
    mark = 'PASS' if ok else 'FAIL'
    if not ok:
        fails += 1
    print(f'[{mark}] {name:<28} {detail}')
print('=' * 72)
print(f'结论：{len(RESULTS) - fails}/{len(RESULTS)} 通过' + ('，全部正常' if fails == 0 else f'，{fails} 项待处理'))
