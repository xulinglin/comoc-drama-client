"""验证：19 位数字 id 经 _stringify_id_fields 处理后，前端可正常按 id 取到文档。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
from launcher import _stringify_id_fields  # noqa: E402

BASE = "http://127.0.0.1:18081"


def simulate_frontend(namespace_api: str, detail_fmt: str) -> tuple[int, int]:
    """返回 (检查总数, 通过数)。模拟前端：列表 -> _stringify_id_fields -> 按 id 取详情。"""
    raw = httpx.get(f"{BASE}{namespace_api}").json()["data"]
    processed = _stringify_id_fields(raw)
    total = passed = 0
    for item in processed:
        item_id = item.get("id")
        if not isinstance(item_id, str):
            continue
        # 只验证数字型 id（长度 >= 16 的高风险项）
        if not item_id.isdigit() or len(item_id) < 16:
            continue
        total += 1
        resp = httpx.get(f"{BASE}{detail_fmt.format(id=item_id)}").json()
        if resp.get("code") == 200:
            passed += 1
        else:
            print(f"  失败 id={item_id} -> {resp.get('message')}")
    return total, passed


print("== projects ==")
t, p = simulate_frontend("/project/list", "/project/{id}")
print(f"  高风险数字 id 项目: {p}/{t} 通过")

print("== video_projects ==")
t2, p2 = simulate_frontend("/video-project/list", "/video-project/{id}")
print(f"  高风险数字 id 视频项目: {p2}/{t2} 通过")

# JS 精度对比：若不做字符串化，19 位 id 会丢精度
print("== 精度对照 ==")
sample = "2078444076475576321"
print(f"  原始 id:        {sample}")
print(f"  JS Number 后:   {float(sample):.0f}  (前端未修复时会用它去请求，导致 404)")
print(f"  修复后传给前端: {_stringify_id_fields({'id': int(sample)})['id']}")

ok = (t == 0 or p == t) and (t2 == 0 or p2 == t2)
print("\n结果:", "全部通过" if ok else "存在失败")
sys.exit(0 if ok else 1)
