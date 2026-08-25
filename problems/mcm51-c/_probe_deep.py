# -*- coding: utf-8 -*-
"""深度数据探查：只读附件，输出结构化报告到 _probe_detail.txt（UTF-8）。"""
import sys, io, json, numpy as np, pandas as pd

OUT = []
def P(*a):
    s = " ".join(str(x) for x in a)
    OUT.append(s)

FILES = [
    ("附件1", r"E:\git_clone\Beacon\problems\mcm51-c\source\附件1：两组位移时序数据-问题1.xlsx"),
    ("附件2", r"E:\git_clone\Beacon\problems\mcm51-c\source\附件2：位移时序数据-问题2.xlsx"),
    ("附件3", r"E:\git_clone\Beacon\problems\mcm51-c\source\附件3：监测数据（训练集与实验集）-问题3.xlsx"),
    ("附件4", r"E:\git_clone\Beacon\problems\mcm51-c\source\附件4：监测数据（训练集与实验集）-问题4.xlsx"),
    ("附件5", r"E:\git_clone\Beacon\problems\mcm51-c\source\附件5：监测数据-问题5.xlsx"),
]

def stats_str(s, name):
    s = pd.to_numeric(s, errors="coerce")
    n = int(s.count())
    nmiss = int(s.isna().sum())
    if n == 0:
        P(f"  [{name}] 全空: n={n} miss={nmiss}")
        return
    P(f"  [{name}] n={n} miss={nmiss}({nmiss/len(s)*100:.2f}%) "
      f"min={s.min():.6g} max={s.max():.6g} mean={s.mean():.6g} median={s.median():.6g} "
      f"std={s.std():.6g} 负值数={(s<0).sum()} 零值数={(s==0).sum()}")

def missing_runs(s):
    m = s.isna()
    runs = []
    start = None
    for i, v in enumerate(m.tolist()):
        if v and start is None: start = i
        if not v and start is not None:
            runs.append((start, i-1, i-start)); start = None
    if start is not None: runs.append((start, len(m)-1, len(m)-start))
    return runs

def missing_summary(s, name, max_print=3):
    runs = missing_runs(s)
    if not runs:
        P(f"  [{name}] 缺失: 无")
        return
    total = sum(r[2] for r in runs)
    lens = [r[2] for r in runs]
    P(f"  [{name}] 缺失段数={len(runs)} 总缺失={total} 段长max={max(lens)} 段长median={np.median(lens):.1f} "
      f"最长段起止索引={max(runs,key=lambda r:r[2])[:2]}")
    if len(runs) <= max_print:
        for r in runs: P(f"     段: 索引[{r[0]}..{r[1]}] 长{r[2]}")
    else:
        P(f"     前{max_print}段: {runs[:max_print]} ... 后2段: {runs[-2:]}")

def outlier_list(s, name, topk=8):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if len(s) < 5: return
    mu, sd = s.mean(), s.std()
    z = (s - mu) / sd if sd > 0 else pd.Series(0.0, index=s.index)
    n3 = int((z.abs() > 3).sum())
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    n_iqr = int(((s < q1 - 1.5*iqr) | (s > q3 + 1.5*iqr)).sum())
    P(f"  [{name}] 3σ外点数={n3}({n3/len(s)*100:.2f}%) IQR外点数={n_iqr}({n_iqr/len(s)*100:.2f}%)")
    if n3 > 0:
        top = z.abs().sort_values(ascending=False).head(topk)
        for idx, zz in top.items():
            P(f"     z={zz:.1f} 行idx={idx} 值={s.loc[idx]:.6g}")

def time_analysis(df, time_col):
    t = pd.to_datetime(df[time_col], errors="coerce")
    n = len(t); nvalid = int(t.notna().sum())
    P(f"  [时间列] 列名='{time_col}' n={n} 有效={nvalid} 唯一={t.nunique()} "
      f"范围=[{t.min()}, {t.max()}]")
    dup = t.duplicated().sum()
    P(f"  重复时间戳数={dup}")
    tt = t.dropna().sort_values()
    diffs = tt.diff().dropna()
    mode = diffs.mode()
    if len(mode):
        md = mode.iloc[0]
        P(f"  相邻差: 众数={md} (n={int((diffs==md).sum())}) 非众数差数={int((diffs!=md).sum())}")
        other = diffs[diffs != md]
        if len(other):
            P(f"    非众数差: min={other.min()} max={other.max()} 最大跳跃位置(idx,差)=" +
              f"{[(int(tt.index[i]), str(other.iloc[i])) for i in other.sort_values(ascending=False).head(5).index if False]}")
            # 直接列前5大跳跃
            big = other.sort_values(ascending=False).head(5)
            for i, v in big.items():
                P(f"      时间差={v} 前一个时间={tt.loc[tt.index[tt.index.get_loc(i)-1]]} 后一个时间={tt.loc[i]}")
        # 期望采样点
        try:
            expected = int((tt.max() - tt.min()) / md) + 1
            P(f"  按众数间隔推算应有 {expected} 个点, 实际 {len(tt)}, 疑似缺失/多余 {len(tt)-expected}")
        except Exception as e:
            P(f"  期望推算失败: {e}")
    else:
        P("  时间差无法计算(无有效数据)")

def run_lengths_of(s):
    """返回 [(值, 段长), ...]"""
    runs = []
    prev = None; cnt = 0
    for v in s.tolist():
        if v == prev: cnt += 1
        else:
            if prev is not None: runs.append((prev, cnt))
            prev = v; cnt = 1
    if prev is not None: runs.append((prev, cnt))
    return runs

# ============================ 附件1 ============================
for tag, f in FILES[:1]:
    P("=" * 100); P(f"### {tag} ###"); P("FILE:", f)
    xl = pd.ExcelFile(f)
    for sh in xl.sheet_names:
        P("-" * 80); P(f"SHEET: {sh}")
        df = pd.read_excel(f, sheet_name=sh)
        P(f"shape={df.shape}")
        P(f"列名={list(df.columns)}")
        P("dtypes:", {c: str(df[c].dtype) for c in df.columns})
        P("前3行:")
        for i in range(min(3, len(df))):
            P("   ", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        P("后3行:")
        for i in range(max(0, len(df)-3), len(df)):
            P("   ", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        time_col = "时间" if "时间" in df.columns else None
        if time_col:
            time_analysis(df, time_col)
        # 数值列统计（排除时间/编号）
        num_cols = [c for c in df.columns if c != time_col and c != "编号" and c != "阶段标签"]
        P("数值列统计(编号列另行处理):")
        for c in num_cols:
            stats_str(df[c], c)
            missing_summary(df[c], c)
            outlier_list(df[c], c)
        if "编号" in df.columns:
            s = pd.to_numeric(df["编号"], errors="coerce")
            P(f"[编号] n={s.count()} miss={s.isna().sum()} min={s.min():.0f} max={s.max():.0f} 连续递增={bool((s.diff().dropna()==1).all())} 差值众数={s.diff().dropna().mode().tolist()}")
        # 附件1 特殊：A/B 对齐与差值
        if "数据A_光纤位移计数据_mm" in df.columns:
            A = pd.to_numeric(df["数据A_光纤位移计数据_mm"], errors="coerce")
            B = pd.to_numeric(df["数据B_振弦式位移计数据_mm"], errors="coerce")
            both = A.notna() & B.notna()
            P(f"[A-B 对齐] A非空={int(A.notna().sum())} B非空={int(B.notna().sum())} 同时非空={int(both.sum())} "
              f"A缺失={int(A.isna().sum())} B缺失={int(B.isna().sum())}")
            D = A - B
            Dv = D[both]
            P(f"[D=A-B] n={len(Dv)} min={Dv.min():.6g} max={Dv.max():.6g} mean={Dv.mean():.6g} median={Dv.median():.6g} std={Dv.std():.6g}")
            corr = A.corr(B)
            P(f"[A,B Pearson] r={corr:.6f} (n={int(both.sum())})")
            t = pd.to_datetime(df["时间"], errors="coerce")
            ts = (t - t.iloc[0]).dt.total_seconds() / 3600.0
            sl = np.polyfit(ts[both], Dv, 1)
            P(f"[D vs t(h)] 线性拟合斜率={sl[0]:.6g} mm/h 截距={sl[1]:.6g} 相关r={np.corrcoef(ts[both], Dv)[0,1]:.6f}")
            # 分10段看 D 均值
            P("D 按时间分10段的均值:")
            for k in range(10):
                seg = both & (ts >= ts.quantile(k/10)) & (ts <= ts.quantile((k+1)/10))
                if seg.sum() > 0:
                    P(f"   段{k}: t≈{ts[seg].mean():.1f}h D均值={D[seg].mean():.4f}")
            # 5个验证点 x(h)
            for x in [7.132, 18.526, 84.337, 123.554, 167.667]:
                tgt = t.iloc[0] + pd.Timedelta(hours=x)
                idx = (t - tgt).abs().idxmin()
                P(f"[验证点] x={x}h → 目标时刻 {tgt}, 最近采样行idx={idx} 时间={t.loc[idx]} "
                  f"A={A.loc[idx]} B={B.loc[idx]} 偏差={(t.loc[idx]-tgt).total_seconds()/60:.1f}min")
            # 也尝试 x=天
            for x in [7.132, 18.526, 84.337, 123.554, 167.667]:
                tgt = t.iloc[0] + pd.Timedelta(days=x)
                if tgt <= t.max():
                    idx = (t - tgt).abs().idxmin()
                    P(f"[验证点-按天解释] x={x}天 → {tgt}, 最近行idx={idx} 时间={t.loc[idx]} A={A.loc[idx]}")
                else:
                    P(f"[验证点-按天解释] x={x}天 → {tgt} 超出序列范围(max={t.max()})")

# ============================ 附件2 ============================
for tag, f in FILES[1:2]:
    P("=" * 100); P(f"### {tag} ###"); P("FILE:", f)
    xl = pd.ExcelFile(f)
    for sh in xl.sheet_names:
        P("-" * 80); P(f"SHEET: {sh}")
        df = pd.read_excel(f, sheet_name=sh)
        P(f"shape={df.shape} 列名={list(df.columns)}")
        P("dtypes:", {c: str(df[c].dtype) for c in df.columns})
        for i in range(min(3, len(df))):
            P("   前", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        for i in range(max(0, len(df)-3), len(df)):
            P("   后", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        s = pd.to_numeric(df["编号"], errors="coerce")
        P(f"[编号] n={s.count()} miss={s.isna().sum()} min={s.min():.0f} max={s.max():.0f} 连续={bool((s.diff().dropna()==1).all())} 差值={s.diff().dropna().value_counts().to_dict()}")
        D = pd.to_numeric(df["表面位移_mm"], errors="coerce")
        stats_str(D, "表面位移_mm")
        missing_summary(D, "表面位移_mm")
        outlier_list(D, "表面位移_mm")
        # 隐含时间
        t0 = pd.Timestamp("2024-05-04 00:00")
        t = t0 + pd.to_timedelta((s - 1) * 10, unit="m")
        P(f"[隐含时间] 首={t.min()} 末={t.max()} 跨度={t.max()-t.min()}")
        v = D.diff()  # mm/10min
        P(f"[速度] n={v.notna().sum()} min={v.min():.6g} max={v.max():.6g} mean={v.mean():.6g} median={v.median():.6g} std={v.std():.6g}")
        P(f"[速度正比] 正差分(加速)占比={(v>0).mean()*100:.2f}% 负差分(回退)占比={(v<0).mean()*100:.2f}% 零占比={(v==0).mean()*100:.2f}%")
        Dc = D.cumsum()  # 不是位移累计，仅用于参考
        # 三阶段粗判: 用累计位移(相对起始) 分位
        D0 = D - D.iloc[0]
        tot = D0.iloc[-1] - D0.iloc[0]
        if tot > 0:
            frac = (D0 - D0.iloc[0]) / tot
            for q in [0.1, 0.33, 0.5, 0.66, 0.9]:
                idxq = (frac - q).abs().idxmin()
                P(f"[累计位移分位] {int(q*100)}% 处 idx={idxq} 编号={s.loc[idxq]} 隐含时间={t.loc[idxq]} 位移={D.loc[idxq]:.6g}")
        # 逐日平均速度（144点/日）
        P("[逐日平均速度 mm/10min (每144点=1天)]:")
        nday = len(D) // 144
        for k in range(nday):
            seg = D.iloc[k*144:(k+1)*144]
            mv = seg.diff().mean()
            P(f"   日{k} (编号{k*144+1}..{(k+1)*144}): 均速={mv:.4f} 起={seg.iloc[0]:.4f} 止={seg.iloc[-1]:.4f}")
        # 最大单步跳变
        if v.notna().any():
            top = v.abs().sort_values(ascending=False).head(8)
            for idx, vv in top.items():
                P(f"   大跳变: idx={idx} 编号={s.loc[idx]} 时刻={t.loc[idx]} Δ={vv:.4f} mm/10min 位移={D.loc[idx]:.6g}")

# ============================ 附件3 ============================
for tag, f in FILES[2:3]:
    P("=" * 100); P(f"### {tag} ###"); P("FILE:", f)
    xl = pd.ExcelFile(f)
    for sh in xl.sheet_names:
        P("-" * 80); P(f"SHEET: {sh}")
        df = pd.read_excel(f, sheet_name=sh)
        P(f"shape={df.shape} 列名={list(df.columns)}")
        P("dtypes:", {c: str(df[c].dtype) for c in df.columns})
        for i in range(min(3, len(df))):
            P("   前", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        for i in range(max(0, len(df)-3), len(df)):
            P("   后", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        s = pd.to_numeric(df["编号"], errors="coerce")
        P(f"[编号] n={s.count()} min={s.min():.0f} max={s.max():.0f} 连续={bool((s.diff().dropna()==1).all())} 差值={s.diff().dropna().value_counts().to_dict()}")
        for c in df.columns:
            if c == "编号": continue
            stats_str(df[c], c)
            missing_summary(df[c], c)
            outlier_list(df[c], c)
        # 相关系数矩阵（成对删除）
        nums = [c for c in df.columns if c != "编号"]
        sub = df[nums].apply(pd.to_numeric, errors="coerce")
        P("[相关系数矩阵(成对删除)]")
        P(sub.corr().round(4).to_string())
        # 空值成对模式：哪些行 表面位移 空
        if "表面位移_mm" in df.columns:
            ms = df["表面位移_mm"].isna()
            P(f"[表面位移缺失] 缺失行数={int(ms.sum())} 占比={ms.mean()*100:.2f}% "
              f"其中深部位移也缺的行数={int((ms & df['深部位移_mm'].isna()).sum())}")

# ============================ 附件4 ============================
for tag, f in FILES[3:4]:
    P("=" * 100); P(f"### {tag} ###"); P("FILE:", f)
    xl = pd.ExcelFile(f)
    for sh in xl.sheet_names:
        P("-" * 80); P(f"SHEET: {sh}")
        df = pd.read_excel(f, sheet_name=sh)
        P(f"shape={df.shape} 列名={list(df.columns)}")
        P("dtypes:", {c: str(df[c].dtype) for c in df.columns})
        for i in range(min(3, len(df))):
            P("   前", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        for i in range(max(0, len(df)-3), len(df)):
            P("   后", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        time_analysis(df, "时间")
        for c in df.columns:
            if c in ("时间", "阶段标签"): continue
            stats_str(df[c], c)
            missing_summary(df[c], c)
            outlier_list(df[c], c)
        if "阶段标签" in df.columns:
            lbl = df["阶段标签"]
            P(f"[阶段标签] 取值分布: {lbl.value_counts(dropna=False).to_dict()}")
            P(f"[阶段标签] 段(值,长度): {run_lengths_of(lbl)}")
        # 爆破列分析
        for bc in ["爆破点距离_m", "单段最大药量_kg"]:
            if bc in df.columns:
                s = pd.to_numeric(df[bc], errors="coerce")
                nn = s.notna()
                P(f"[爆破列 {bc}] 非空={int(nn.sum())}({nn.mean()*100:.2f}%) 空={int(s.isna().sum())}({s.isna().mean()*100:.2f}%)")
                if nn.sum() > 0:
                    P(f"  非空值: min={s.min():.6g} max={s.max():.6g} mean={s.mean():.6g} median={s.median():.6g} std={s.std():.6g} 唯一值数={s.nunique()}")
                    P(f"  非空行时间(前20+后5):")
                    rows = df[nn]
                    for _, r in rows.head(20).iterrows():
                        P(f"    {r['时间']} | {bc}={r[bc]:.6g}")
                    for _, r in rows.tail(5).iterrows():
                        P(f"    {r['时间']} | {bc}={r[bc]:.6g}")
                    P(f"  非空段(连续非空的run): {run_lengths_of(nn.astype(int))}")
        # 两列同时非空/单边
        if "爆破点距离_m" in df.columns and "单段最大药量_kg" in df.columns:
            a = df["爆破点距离_m"].notna(); b = df["单段最大药量_kg"].notna()
            P(f"[爆破两列一致性] 双非空={int((a&b).sum())} 仅距离非空={int((a&~b).sum())} 仅药量非空={int((~a&b).sum())} 双空={int((~a&~b).sum())}")
            # 非爆破时刻核对：空行中 微震/降雨 分布
            P(f"[空值行特征] 微震事件数>0的行中爆破非空数={int((df['微震事件数']>0).sum())} 微震>0且爆破非空={int(((df['微震事件数']>0)&a).sum())} "
              f"降雨>0且爆破非空={int(((df['降雨量_mm']>0)&a).sum())}")
        nums = [c for c in df.columns if c not in ("时间", "阶段标签")]
        sub = df[nums].apply(pd.to_numeric, errors="coerce")
        P("[相关系数矩阵(成对删除)]")
        P(sub.corr().round(4).to_string())

# ============================ 附件5 ============================
for tag, f in FILES[4:5]:
    P("=" * 100); P(f"### {tag} ###"); P("FILE:", f)
    xl = pd.ExcelFile(f)
    for sh in xl.sheet_names:
        P("-" * 80); P(f"SHEET: {sh}")
        df = pd.read_excel(f, sheet_name=sh)
        P(f"shape={df.shape} 列名={list(df.columns)}")
        P("dtypes:", {c: str(df[c].dtype) for c in df.columns})
        for i in range(min(3, len(df))):
            P("   前", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        for i in range(max(0, len(df)-3), len(df)):
            P("   后", i, {c: repr(df[c].iloc[i]) for c in df.columns})
        time_analysis(df, "时间")
        for c in df.columns:
            if c == "时间": continue
            stats_str(df[c], c)
            missing_summary(df[c], c)
            outlier_list(df[c], c)
        for bc in ["爆破点距离_m", "单段最大药量_kg"]:
            if bc in df.columns:
                s = pd.to_numeric(df[bc], errors="coerce")
                nn = s.notna()
                P(f"[爆破列 {bc}] 非空={int(nn.sum())}({nn.mean()*100:.2f}%) 空={int(s.isna().sum())}({s.isna().mean()*100:.2f}%)")
                if nn.sum() > 0:
                    P(f"  非空值: min={s.min():.6g} max={s.max():.6g} mean={s.mean():.6g} median={s.median():.6g} std={s.std():.6g} 唯一值数={s.nunique()}")
                    P(f"  非空行时间(前20+后5):")
                    rows = df[nn]
                    for _, r in rows.head(20).iterrows():
                        P(f"    {r['时间']} | {bc}={r[bc]:.6g}")
                    for _, r in rows.tail(5).iterrows():
                        P(f"    {r['时间']} | {bc}={r[bc]:.6g}")
                    P(f"  非空段(连续非空的run): {run_lengths_of(nn.astype(int))}")
        if "爆破点距离_m" in df.columns and "单段最大药量_kg" in df.columns:
            a = df["爆破点距离_m"].notna(); b = df["单段最大药量_kg"].notna()
            P(f"[爆破两列一致性] 双非空={int((a&b).sum())} 仅距离非空={int((a&~b).sum())} 仅药量非空={int((~a&b).sum())} 双空={int((~a&~b).sum())}")
            P(f"[空值行特征] 微震>0行数={int((df['微震事件数']>0).sum())} 微震>0且爆破非空={int(((df['微震事件数']>0)&a).sum())} "
              f"降雨>0且爆破非空={int(((df['降雨量_mm']>0)&a).sum())}")
        nums = [c for c in df.columns if c != "时间"]
        sub = df[nums].apply(pd.to_numeric, errors="coerce")
        P("[相关系数矩阵(成对删除)]")
        P(sub.corr().round(4).to_string())

report = "\n".join(OUT)
with open(r"E:\git_clone\Beacon\problems\mcm51-c\_probe_detail.txt", "w", encoding="utf-8") as fh:
    fh.write(report)
print("REPORT_LINES:", len(OUT))
print("WRITTEN OK")
