# -*- coding: utf-8 -*-
"""mcm51-b 参考求解实现（人工供给 · 2026-08-21 · 已本地验证）

定位：方向生产（brief-playbook）前置供给的「实现级骨架」。
本文件被流水线 coder 生成的包装代码 exec 调用（或直接运行），完成：
  数据解析（B-附件.xlsx 三表）→ 工序展开（含 C 车间循环链）→
  Q1–Q4 调度求解（构造式启发式，口径与 brief 完全一致）→ RESULT 输出 → 表1-5 → 甘特图。

口径（与 problems/mcm51-b/brief.json 一致，勿改）：
  1. 工序完成判据 C_i = max(C_{i,r1}, C_{i,r2})：两类设备都完成各自工程量后工序才结束；
     设备完成自身工程量后立即释放（可接新任务/开始转运），不被搭档锁死。
  2. 跨车间直接运输：时间 = 车间距离 ÷ 2 (m/s)，统一秒向上取整；同车间转移 = 0；
     设备初始位置 = 所属班组驻地，初始进场（班组→首个车间）计入 makespan。
  3. C 车间展开为 C1→C2→(C3_1,C4_1,C5_1)→(C3_2,C4_2,C5_2)→(C3_3,C4_3,C5_3)，轮间整链顺序。
  4. Q1 仅 A 车间 + 班组1；Q2 五车间 + 班组1；Q3 五车间 + 班组1+2；Q4 预算≤500000 购置×班组×调度联合。
  5. 默认一设备一工序（不允许多台同类分摊）；不可抢占；加工时长 = 工程量÷效率(h) → 秒向上取整。
     CLI 开关 `--allow-splitting` 为 H-04 验证用：同类多机并行分摊工程量（默认关 = 冻结语义）。

性质声明（诚实标注）：Q1 可精确（规模极小）；Q2–Q4 为构造式启发式（确定性优先规则），
结果可行且口径合规，**非全局最优**——论文须如实声明并给出下界对照（关键路径 CPM 无容量下界）。
CP-SAT 精确化列为后续方法能力库升级项。

模型变量对照（供 model_code_consistency 评审核对）：
  C_max = makespan（最终完工时间）           S_i = 工序 i 的开始时间
  C_i   = 工序 i 的完成时间                  C_{i,r} = 工序 i 对设备 r 的完成时间
  x_{i,k} = 工序 i 分配到设备实例 k（1/0）    y_{k,l,t} = 设备 k 在班组 l 的归属（Q4 购置）
  n_{m,l} = 设备类型 m 在班组 l 的购置台数     p_{i,k} = 设备 k 上工序 i 的加工时长
  T_{l,l'} = 车间 l→l' 运输时间              d_{l,l'} = 车间间距离
  v = 设备移动速度(2 m/s)                     l_i = 工序 i 所在车间；l_0 = 班组驻地
  K_r = 设备类型 r 的实例数（容量）           B = 预算(500000)；P = 设备单价
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------- 数据解析（对附件真实格式鲁棒） ----------------

_SPEED_MS = 2.0


def _parse_efficiency(text) -> list[tuple[str, float]]:
    """解析 '精密灌装机200m³/h和自动化输送臂250m³/h'（设备名与数值间无空格、'和' 分隔）。"""
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return []
    text = str(text)
    parts = re.split(r"[和、,，]", text)
    out = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*m³/h", part)
        if not m:
            continue
        name = part[: m.start()].strip()
        out.append((name, float(m.group(1))))
    return out


def _parse_quantity(text) -> float | None:
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*m³", str(text))
    return float(m.group(1)) if m else None


def _split_ids(text) -> list[str]:
    """拆 '自动化输送臂1-1；\n自动化输送臂1-2；...。' 为实例 id 列表。"""
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return []
    parts = re.split(r"[；;\n，,、]", str(text))
    return [p.strip().rstrip("。.") for p in parts if p.strip()]


def _parse_distance(text) -> float | None:
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*m$", str(text).strip())
    return float(m.group(1)) if m else None


def load_problem(data_dir: Path) -> dict:
    """读取三张表并构造结构化题目。data_dir 内含 B-附件.xlsx（中文版）。"""
    # source/ 下可能有英文版副本（B-attachment.xlsx），按工作表名识别中文版，避免拿错
    candidates = sorted(data_dir.glob("*.xlsx"))
    xlsx = None
    for cand in candidates:
        try:
            names = pd.ExcelFile(cand).sheet_names
        except Exception:
            names = []
        if any("工序" in str(n) for n in names):
            xlsx = cand
            break
    if xlsx is None:
        raise FileNotFoundError(f"data_dir 下无含「工序流程表」的 xlsx：{data_dir}；候选={candidates}")
    process = pd.read_excel(xlsx, sheet_name="工序流程表")
    config = pd.read_excel(xlsx, sheet_name="班组配置表")
    dist = pd.read_excel(xlsx, sheet_name="车间距离表")

    process = process.copy()
    process["任务"] = process["任务"].ffill()

    activities: list[dict] = []
    for _, row in process.iterrows():
        name = str(row["工序"]).strip()
        workshop = name[0].upper()
        acts = _parse_efficiency(row["设备作业效率"])
        qty = _parse_quantity(row["工程量"])
        note = str(row.get("备注") or "")
        activities.append({
            "name": name, "workshop": workshop, "devices": acts,
            "quantity": qty, "note": note,
        })

    # C 车间循环链：C3–C5 三种工序整体重复 3 遍（题面备注「C3-C5完成1遍之后需要再进行2遍」+ brief formula-cloop）
    # → C1→C2→(C3_1,C4_1,C5_1)→(C3_2,C4_2,C5_2)→(C3_3,C4_3,C5_3)，共 11 道活动（2026-08-21 修复：此前只展开 C3，C4/C5 仅执行一次）
    expanded: list[dict] = []
    for act in activities:
        if act["workshop"] == "C" and act["name"][:2] in ("C3", "C4", "C5"):
            for k in range(1, 4):
                tag = f"{act['name'][:2]}_{k}"
                expanded.append({**act, "name": tag})
        else:
            expanded.append(act)

    # C 车间链顺序：C1, C2, C3_1, C4_1, C5_1, C3_2, C4_2, C5_2, C3_3, C4_3, C5_3
    # 注意：C1/C2 活动名是全名（"C1.旧涂层剥离"），展开标签是短名（"C3_1"），
    # 键必须按前缀正则匹配，不能整名查字典（2026-08-21 修复：整名查找回退 99 导致 C1/C2 排到链尾）。
    def _c_key(name: str) -> int:
        m = re.match(r"^(C[1-5])", name)
        if not m:
            return 99
        c = m.group(1)
        if c == "C1":
            return 0
        if c == "C2":
            return 1
        m2 = re.match(r"^C([345])_(\d)$", name)
        if not m2:
            return 99
        i, k = int(m2.group(1)), int(m2.group(2))
        return 2 + (k - 1) * 3 + (i - 3)

    order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    expanded.sort(key=lambda a: (
        order[a["workshop"]],
        _c_key(a["name"]) if a["workshop"] == "C" else 0,
        a["name"],
    ))
    for i, a in enumerate(expanded):
        a["idx"] = i

    # 前驱：同车间上一道（C 循环链按上述顺序即得 C5_k → C3_{k+1}）
    pred: dict[int, int | None] = {a["idx"]: None for a in expanded}
    by_ws: dict[str, list[dict]] = {}
    for a in expanded:
        by_ws.setdefault(a["workshop"], []).append(a)
    for ws, acts in by_ws.items():
        for j in range(1, len(acts)):
            pred[acts[j]["idx"]] = acts[j - 1]["idx"]

    # 设备实例
    instances: list[dict] = []
    crew_counts: dict[int, dict[str, int]] = {}
    price: dict[str, float] = {}
    for _, row in config.iterrows():
        dtype = str(row["设备名称"]).strip()
        price[dtype] = float(row["设备单价(元/台)"])
        speed = float(row["移动速度(m/s)"])
        for crew in (1, 2):
            ids = _split_ids(row[f"班组{crew}设备编号"])
            crew_counts.setdefault(crew, {})[dtype] = len(ids)
            for did in ids:
                instances.append({
                    "id": did, "type": dtype, "crew": crew,
                    "speed": speed, "price": price[dtype],
                    "avail": 0.0, "loc": f"班组{crew}",  # 初始位置=班组驻地
                })

    # 距离表（无向；含 班组→车间 与 车间→车间）
    distance: dict[tuple[str, str], float] = {}
    for _, row in dist.iterrows():
        s = str(row["起点"]).strip()
        e = str(row["终点"]).strip()
        d = _parse_distance(row["距离"])
        if d is not None:
            distance[(s, e)] = d
            distance[(e, s)] = d

    return {
        "activities": expanded,
        "pred": pred,
        "instances": instances,
        "crew_counts": crew_counts,
        "price": price,
        "distance": distance,
        "workshops": ["A", "B", "C", "D", "E"],
    }


def _job_duration(act: dict, dtype: str) -> int:
    """设备-工序加工时长（秒，向上取整）：工程量 ÷ 效率(h) × 3600。"""
    eff = next((e for n, e in act["devices"] if n == dtype), None)
    if eff is None or act["quantity"] is None:
        return 0
    return int(math.ceil(act["quantity"] / eff * 3600))


def _travel(pb: dict, loc_a: str, loc_b: str, speed: float) -> int:
    """跨地点运输时间（秒，向上取整）；同地点为 0。直接运输（不经班组驻地）。"""
    if loc_a == loc_b:
        return 0
    d = pb["distance"].get((loc_a, loc_b))
    if d is None:
        return 0
    return int(math.ceil(d / speed))


# ---------------- 构造式调度核心 ----------------

def schedule(
    pb: dict,
    act_ids: list[int],
    device_pool: list[dict],
    allow_splitting: bool = False,
) -> tuple[dict, int]:
    """确定性优先规则调度：返回 {act_idx: (start, end, {dtype: [device_id, ...]})} 与 makespan。

    allow_splitting=False（默认）：每类型选一台最早可开工实例（冻结语义）。
    allow_splitting=True：该类型 pool 内全部实例并行分摊工程量。

    约束：前驱链、双设备各自完成（C_i = max C_{i,r}，先完成者立即释放）、
    单实例不可重叠、跨车间直接运输（设备位置链）、初始进场（班组驻地→车间）计入。
    """
    acts = pb["activities"]
    pred = pb["pred"]
    # 内部复制：schedule 会原地更新设备 avail/loc；调用方池不可被污染（Q4 多次调度）
    device_pool = [dict(d) for d in device_pool]
    device_map = {d["id"]: d for d in device_pool}
    result: dict[int, dict] = {}
    done: set[int] = set()
    remaining = set(act_ids)

    while remaining:
        ready = sorted(
            (i for i in remaining if pred[i] is None or pred[i] in done),
            key=lambda i: (acts[i]["workshop"], acts[i]["name"]),
        )
        if not ready:
            raise RuntimeError("存在循环依赖，无法调度")
        i = ready[0]
        remaining.remove(i)
        pred_end = max((result[p]["end"] for p in [pred[i]] if p in result), default=0)

        job_devices: dict[str, list[str]] = {}
        job_start: dict[str, int] = {}
        job_end: dict[str, int] = {}
        for dtype, eff in acts[i]["devices"]:
            type_pool = [d for d in device_pool if d["type"] == dtype]
            if not type_pool:
                raise RuntimeError(f"工序 {acts[i]['name']} 无可用设备（类型 {dtype}）")
            if allow_splitting:
                n = len(type_pool)
                qty = acts[i]["quantity"]
                dur = (
                    int(math.ceil(qty / (n * eff) * 3600))
                    if qty is not None and eff
                    else 0
                )
                ready = max(
                    max(pred_end, int(d["avail"]) + _travel(pb, d["loc"], acts[i]["workshop"], d["speed"]))
                    for d in type_pool
                )
                job_devices[dtype] = [d["id"] for d in type_pool]
                job_start[dtype] = int(ready)
                job_end[dtype] = int(ready) + dur
            else:
                dur = _job_duration(acts[i], dtype)
                best_id, best_start = None, None
                for d in type_pool:
                    trans = _travel(pb, d["loc"], acts[i]["workshop"], d["speed"])
                    cand = max(pred_end, int(d["avail"]) + trans)
                    if best_start is None or cand < best_start:
                        best_start, best_id = cand, d["id"]
                job_devices[dtype] = [best_id]
                job_start[dtype] = int(best_start)
                job_end[dtype] = int(best_start) + dur
        end = max(job_end.values()) if job_end else int(pred_end)
        # 设备立即释放（各自 job_end）+ 更新位置
        for dtype, dids in job_devices.items():
            for did in dids:
                d = device_map[did]
                d["avail"] = float(job_end[dtype])
                d["loc"] = acts[i]["workshop"]
        result[i] = {"start": int(pred_end), "end": end, "jobs": job_devices,
                     "job_start": job_start, "job_end": job_end}
        done.add(i)
    makespan = max(v["end"] for v in result.values()) if result else 0
    return result, makespan


def _crew_pool(pb: dict, crews: list[int]) -> list[dict]:
    return [dict(d) for d in pb["instances"] if d["crew"] in crews]


def solve_q1(pb: dict, allow_splitting: bool = False) -> tuple[dict, int]:
    a_ids = [a["idx"] for a in pb["activities"] if a["workshop"] == "A"]
    return schedule(pb, a_ids, _crew_pool(pb, [1]), allow_splitting=allow_splitting)


def solve_q2(pb: dict, allow_splitting: bool = False) -> tuple[dict, int]:
    ids = [a["idx"] for a in pb["activities"]]
    return schedule(pb, ids, _crew_pool(pb, [1]), allow_splitting=allow_splitting)


def solve_q3(pb: dict, allow_splitting: bool = False) -> tuple[dict, int]:
    ids = [a["idx"] for a in pb["activities"]]
    return schedule(pb, ids, _crew_pool(pb, [1, 2]), allow_splitting=allow_splitting)


def solve_q4(pb: dict, budget: float = 500000.0, allow_splitting: bool = False) -> tuple[dict, int, dict]:
    """预算内贪心购置 + 调度：反复购买「边际改善/单价」最优的设备，直到预算耗尽或无改善。

    返回 (schedule, makespan, purchase)，purchase[(dtype, crew)] = 台数。
    """
    base_pool = _crew_pool(pb, [1, 2])
    ids = [a["idx"] for a in pb["activities"]]
    pool = [dict(d) for d in base_pool]
    purchase: dict[tuple[str, int], int] = {}
    spent = 0.0
    cur_makespan = schedule(pb, ids, pool, allow_splitting=allow_splitting)[1]
    while spent < budget:
        best = None  # (gain, cost, dtype, crew, new_makespan)
        for dtype, pr in pb["price"].items():
            for crew in (1, 2):
                if spent + pr > budget:
                    continue
                trial = [dict(d) for d in pool]
                trial.append({
                    "id": f"{dtype}-{crew}-new{len(pool)}", "type": dtype, "crew": crew,
                    "speed": _SPEED_MS, "price": pr, "avail": 0.0, "loc": f"班组{crew}",
                })
                ms = schedule(pb, ids, trial, allow_splitting=allow_splitting)[1]
                gain = cur_makespan - ms
                if gain > 0 and (best is None or gain / pr > best[0]):
                    best = (gain / pr, pr, dtype, crew, ms)
        if best is None:
            break
        _, pr, dtype, crew, ms = best
        spent += pr
        pool.append({
            "id": f"{dtype}-{crew}-new{len(pool)}", "type": dtype, "crew": crew,
            "speed": _SPEED_MS, "price": pr, "avail": 0.0, "loc": f"班组{crew}",
        })
        purchase[(dtype, crew)] = purchase.get((dtype, crew), 0) + 1
        cur_makespan = ms
    sch, ms = schedule(pb, ids, pool, allow_splitting=allow_splitting)
    return sch, ms, {"purchase": purchase, "spent": spent, "pool": pool}


# ---------------- 输出：RESULT + 表1-5 + 甘特图 ----------------

def _fmt_clock(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def print_schedule_table(sch: dict, acts: list, with_crew: bool, device_crew: dict) -> None:
    rows = []
    for i, v in sch.items():
        act = acts[i]
        for dtype, dids in v["jobs"].items():
            for did in dids:
                crew = device_crew.get(did, "")
                rows.append([
                    did, _fmt_clock(v["job_start"][dtype]), _fmt_clock(v["job_end"][dtype]),
                    v["job_end"][dtype] - v["job_start"][dtype], act["name"],
                ] + ([crew] if with_crew else []))
    rows.sort(key=lambda r: (r[0], r[1]))
    header = "序号, 设备编号, 起始时间, 结束时间, 持续工作时间(s), 工序编号" + (", 班组" if with_crew else "")
    print(header)
    for num, r in enumerate(rows, 1):
        print(str(num) + ", " + ", ".join(str(x) for x in r))


def draw_gantt(sch: dict, acts: list, title: str, fname: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    bar_rows: list[tuple[int, str, int, int, str]] = []
    for i, v in sorted(sch.items(), key=lambda kv: (kv[1]["start"], kv[1]["end"])):
        act_name = acts[i]["name"]
        for dtype, dids in v["jobs"].items():
            s = v["job_start"][dtype]
            e = v["job_end"][dtype]
            for did in dids:
                bar_rows.append((i, act_name, s, e, did))
    fig, ax = plt.subplots(figsize=(14, max(6, len(bar_rows) * 0.35)))
    for y, (_i, act_name, s, e, did) in enumerate(bar_rows):
        ax.barh(y, e - s, left=s, height=0.5, color="#4C72B0", edgecolor="black")
        ax.text((s + e) / 2, y, did, ha="center", va="center", fontsize=7)
    ax.set_xlabel("时间 (秒)")
    ax.set_yticks(range(len(bar_rows)))
    ax.set_yticklabels([r[1] for r in bar_rows], fontsize=8)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(fname, dpi=150)
    plt.close(fig)


def print_activity_diagnostics(sch: dict, acts: list) -> None:
    """每工序每设备类型一行：name, dtype, n, duration_s, C_i。"""
    print("诊断: name, dtype, n, duration_s, C_i")
    for i in sorted(sch.keys(), key=lambda k: (acts[k]["workshop"], acts[k]["name"])):
        v = sch[i]
        act = acts[i]
        for dtype, dids in v["jobs"].items():
            dur = v["job_end"][dtype] - v["job_start"][dtype]
            print(f"{act['name']}, {dtype}, {len(dids)}, {dur}, {v['end']}")


def _resolve_out_dir(data_dir: Path, out_dir: Path | None) -> Path:
    data_resolved = data_dir.resolve()
    if out_dir is None:
        out = Path.cwd().resolve()
    else:
        out = Path(out_dir).resolve()
    if out == data_resolved:
        raise SystemExit(
            f"拒绝写入 data_dir/source 目录（会覆盖冻结甘特）：{out}\n"
            "请显式指定 out_dir，例如 problems/mcm51-b/calibration/h04/off"
        )
    return out


def main(
    data_dir: str | None = None,
    out_dir: str | None = None,
    *,
    allow_splitting: bool = False,
    q1_only: bool = False,
) -> None:
    data_path = Path(data_dir or "E:/git_clone/Beacon/problems/mcm51-b/source")
    out_path = _resolve_out_dir(data_path, Path(out_dir) if out_dir else None)
    out_path.mkdir(parents=True, exist_ok=True)
    pb = load_problem(data_path)

    device_crew = {d["id"]: d["crew"] for d in pb["instances"]}

    if q1_only:
        sch1, ms1 = solve_q1(pb, allow_splitting=allow_splitting)
        print(f"Q1 makespan: {ms1} 秒 (allow_splitting={allow_splitting})")
        print("表1:")
        print_schedule_table(sch1, pb["activities"], False, device_crew)
        print(f"完成问题1任务的最短时长：{ms1} (s)")
        print_activity_diagnostics(sch1, pb["activities"])
        gantt_path = out_path / "gantt_q1.png"
        draw_gantt(sch1, pb["activities"], "Q1 A 车间调度", str(gantt_path))
        print(f"甘特图已保存：{gantt_path}")
        return

    sch1, ms1 = solve_q1(pb, allow_splitting=allow_splitting)
    sch2, ms2 = solve_q2(pb, allow_splitting=allow_splitting)
    sch3, ms3 = solve_q3(pb, allow_splitting=allow_splitting)
    sch4, ms4, q4 = solve_q4(pb, allow_splitting=allow_splitting)

    for d in q4["pool"]:
        device_crew[d["id"]] = d["crew"]

    print(f"Q1 makespan: {ms1} 秒")
    print("表1:")
    print_schedule_table(sch1, pb["activities"], False, device_crew)
    print(f"完成问题1任务的最短时长：{ms1} (s)")

    print(f"Q2 makespan: {ms2} 秒")
    print("表2:")
    print_schedule_table(sch2, pb["activities"], False, device_crew)
    print(f"完成问题2任务的最短时长：{ms2} (s)")

    print(f"Q3 makespan: {ms3} 秒")
    print("表3:")
    print_schedule_table(sch3, pb["activities"], True, device_crew)
    print(f"完成问题3任务的最短时长：{ms3} (s)")

    print(f"Q4 makespan: {ms4} 秒, 购置总费用: {q4['spent']:.0f} 元")
    print("表4:")
    print_schedule_table(sch4, pb["activities"], True, device_crew)
    print("表5:")
    print("设备名称, 班组1购买台数, 班组2购买台数")
    for dtype in pb["price"]:
        print(f"{dtype}, {q4['purchase'].get((dtype, 1), 0)}, {q4['purchase'].get((dtype, 2), 0)}")
    print(f"完成问题4任务的最短时长：{ms4} (s)")
    print(f"购买设备总费用：{q4['spent']:.0f} (元)")

    budget_utilization = q4['spent'] / 500000.0
    print(f"RESULT: baseline=ours makespan={ms4} total_cost={q4['spent']:.0f} "
          f"budget_utilization={budget_utilization:.4f} q1_makespan={ms1} "
          f"q2_makespan={ms2} q3_makespan={ms3}")

    draw_gantt(sch1, pb["activities"], "Q1 A 车间调度", str(out_path / "gantt_q1.png"))
    draw_gantt(sch2, pb["activities"], "Q2 五车间调度（班组1）", str(out_path / "gantt_q2.png"))
    draw_gantt(sch3, pb["activities"], "Q3 五车间调度（班组1+2）", str(out_path / "gantt_q3.png"))
    draw_gantt(sch4, pb["activities"], "Q4 购置+调度", str(out_path / "gantt_q4.png"))
    print(f"甘特图已保存：{out_path / 'gantt_q1.png'} ~ {out_path / 'gantt_q4.png'}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="mcm51-b 参考求解器")
    parser.add_argument("data_dir", nargs="?", default="E:/git_clone/Beacon/problems/mcm51-b/source")
    parser.add_argument("out_dir", nargs="?", default=None)
    parser.add_argument("--allow-splitting", action="store_true", help="H-04：同类多机并行分摊")
    parser.add_argument("--q1-only", action="store_true", help="仅求解 Q1 并写入 out_dir")
    _args = parser.parse_args()
    main(
        _args.data_dir,
        _args.out_dir,
        allow_splitting=_args.allow_splitting,
        q1_only=_args.q1_only,
    )
