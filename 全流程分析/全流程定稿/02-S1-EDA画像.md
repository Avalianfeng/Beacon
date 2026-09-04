# 02 · EDA 画像

> **第一幕。** 总图：[00-正式闭环](00-正式闭环.md)。

## 谁 / 产物 / 人闸

| | |
|---|---|
| 谁 | 脚本 EDA + 人看图 |
| 产物 | `data_profile.md`、`eda/附件N.png`（本题另有概览四合一） |
| 人闸 | 人说「对撞够用这些图」或点名补图 |

## 怎么做（现行）

- 本机脚本扫附件结构/量级/对齐；出每附件一图  
- 可拼图外发：  
  `python scripts/pack_external_upload.py --dir problems/<题>/eda --glob-png "附件*.png" --stem 概览四合一 --md-skip`

## cumcm23-c 实况

- ☑ `data_profile.md`、`eda/附件1–4.png`、`概览四合一.png`、`_make_overview.py`  
- 大附件无官方抽样 CLI → 本题用脚本走通（◇ 未建通用命令，全流程后再议）

## 旧版

docs/D-007 强制产物表 → 参考；真跑以本题 `eda/` 为准。
