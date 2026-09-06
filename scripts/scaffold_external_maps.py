"""为题目脚手架「认知地图集/外部」目录（学-37 契约）。

默认只建 V1；要多视角再加 --versions V2。
已存在的文件默认跳过（--force 才覆盖）。

示例：
  python scripts/scaffold_external_maps.py --problem problems/cumcm24-c
  python scripts/scaffold_external_maps.py --problem problems/cumcm24-c --versions V1 V2
"""
from __future__ import annotations

import argparse
from pathlib import Path

INDEX_MD = """# 共享切片索引

| 切片ID | 文件 | 口径一句话 | 首次产出 | 复用 |
|---|---|---|---|---|
| （尚无） | | | | |

规则：新切片先落 `切片/` 再登记本表；V 侧 `索取/轮N/清单.md` 写 **切片ID**（如 `S001`）或 `_共享/切片/<文件>`。
pack 用：`python scripts/pack_external_upload.py --dir …/V*/索取/轮N --stem 给第二家-V*-轮N --resolve-shared`
"""

SHARED_README = """# 外部 · _共享

可复用层（跨 V）：

- `scripts/` — 通用算子（无某 V 私货）
- `切片/` — 稳定口径产物 + `_索引.md`

**不要**把某 V 的【索取】对话、打包成品、地图放这里。
完整索取档案在 `V*/索取/`。契约：`全流程分析/prompts/外部/说明-索取目录契约.md`
"""

SHARED_SCRIPTS_README = """# _共享/scripts

每个脚本写清：输入 / 输出路径约定 / 何时用。
视角专用编排放 `V*/索取/scripts/`，只调用本目录算子。
"""

清单_MD = """# {ver} · 索取 · {round} · 清单

| 序号 | 【索取】摘要 | 文件（本目录文件名 / 切片ID / `_共享/切片/…`） | 用途 |
|---|---|---|---|
| （尚无） | | | |

回填后：共享切片登记 `_共享/切片/_索引.md`；本表写 ID。
打包（自动解析共享，无需手拷进本目录）：

```text
python scripts/pack_external_upload.py --dir <本目录> --stem 给第二家-{ver}-{round} --resolve-shared
```

成品默认进 `../../外发归档/`。
"""

V_索取_README = """# {ver} · 索取总账

| 轮次 | 条目数 | 状态 |
|---|---|---|
| 轮1 | 0 | 未开 |
| 轮2 | 0 | — |

完整档案在本目录；可复用切片见 `../../_共享/`。
"""

V_README = """# {ver}

| 项 | 值 |
|---|---|
| 模型 | （待填） |
| 视角标签 | （待填） |
| 事实包 | `source/方向生产-提示词包.md` |
| 状态 | 未开跑 |

开跑前四行填齐。禁喂其他 V 的地图/轮次/索取叙事。
"""

EXTERNAL_README = """# {slug} · 认知地图集 / 外部

- 多视角：`全流程分析/prompts/外部/说明-多视角版本.md`
- 索取分家：`全流程分析/prompts/外部/说明-索取目录契约.md`

```text
外部/
  _共享/     ← 可复用 scripts + 切片 + _索引
  V*/        ← 索取/ · 轮次/ · 外发归档/ · 地图/
```

脚手架：`python scripts/scaffold_external_maps.py --problem problems/{slug}`

## 版本登记

| 版本 | 模型 | 视角标签 | 状态 | 闭环地图 |
|---|---|---|---|---|
{version_rows}

本地可读 `_共享/切片`；禁读所有 `V*/地图|轮次|外发归档|索取`。
"""

MAPS_README = """# {slug} · 认知地图集

| 子目录 | 用途 |
|---|---|
| `外部/` | `_共享/` + 多视角 `V*` |
| `本地/` | 多版本 `V*` |
| `diff/` | Diff |
| `清点/` | 拍板后 |

脚手架外部树：`python scripts/scaffold_external_maps.py --problem problems/{slug}`
"""

LOCAL_README = """# {slug} · 本地

| 版本 | 状态 |
|---|---|
| V1 | 未派 |

外部禁读：`../外部/V*/地图|轮次|外发归档|索取`。  
外部可读：`../外部/_共享/切片`。
"""

LOCAL_V_README = """# 本地 · V1

干净探索工作区。产出：`_证据卡.md` + `认知地图-本地.md`。
"""


def _write(path: Path, text: str, *, force: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return f"skip {path}"
    body = text if text.endswith("\n") else text + "\n"
    path.write_text(body, encoding="utf-8")
    return f"write {path}"


def scaffold(problem: Path, versions: list[str], *, force: bool) -> list[str]:
    slug = problem.name
    maps = problem / "认知地图集"
    external = maps / "外部"
    shared = external / "_共享"
    logs: list[str] = []

    logs.append(_write(maps / "README.md", MAPS_README.format(slug=slug), force=force))
    version_rows = "\n".join(
        f"| {v} | （待填） | （待填） | 未开跑 | — |" for v in versions
    )
    logs.append(
        _write(
            external / "README.md",
            EXTERNAL_README.format(slug=slug, version_rows=version_rows),
            force=force,
        )
    )
    logs.append(_write(shared / "README.md", SHARED_README, force=force))
    logs.append(_write(shared / "scripts" / "README.md", SHARED_SCRIPTS_README, force=force))
    logs.append(_write(shared / "切片" / "_索引.md", INDEX_MD, force=force))

    for ver in versions:
        vroot = external / ver
        logs.append(_write(vroot / "README.md", V_README.format(ver=ver), force=force))
        for sub in ("轮次", "外发归档", "地图"):
            d = vroot / sub
            d.mkdir(parents=True, exist_ok=True)
            keep = d / ".gitkeep"
            if not keep.exists():
                keep.write_text("", encoding="utf-8")
                logs.append(f"mkdir {d}")
        suqiu = vroot / "索取"
        logs.append(_write(suqiu / "README.md", V_索取_README.format(ver=ver), force=force))
        (suqiu / "scripts").mkdir(parents=True, exist_ok=True)
        for rnd in ("轮1", "轮2"):
            logs.append(
                _write(
                    suqiu / rnd / "清单.md",
                    清单_MD.format(ver=ver, round=rnd),
                    force=force,
                )
            )

    local = maps / "本地"
    logs.append(_write(local / "README.md", LOCAL_README.format(slug=slug), force=force))
    logs.append(_write(local / "V1" / "README.md", LOCAL_V_README, force=force))
    return logs


def main() -> None:
    parser = argparse.ArgumentParser(description="脚手架认知地图集/外部（_共享 + V*）")
    parser.add_argument("--problem", type=Path, required=True, help="题目目录 problems/<题>")
    parser.add_argument(
        "--versions",
        nargs="+",
        default=["V1"],
        help="要建的外部视角（默认仅 V1；需要时再加 V2）",
    )
    parser.add_argument("--force", action="store_true", help="覆盖已有 README/清单")
    args = parser.parse_args()
    problem = args.problem.resolve()
    if not problem.is_dir():
        raise SystemExit(f"题目目录不存在：{problem}")
    for line in scaffold(problem, args.versions, force=args.force):
        print(line)
    print("[OK] 外部脚手架就绪。开 V2：再跑本脚本加 --versions V2（或 V1 V2）。")


if __name__ == "__main__":
    main()
