# Beacon Web UI

该目录包含 Beacon 的本地 Web 工作台与 Node.js API 服务：

- `server.mjs`：健康检查、运行控制、进度聚合、日志流与产物读取；
- `index.html`、`app.js`、`styles.css`：面向非技术用户的简化界面；
- `lib/progress.mjs`：把 supervisor / failure / checkpoint 翻译成中文进度；
- `assets/`：Logo 与页面图片资源。

## 怎么用（队员向）

1. 在项目根目录启动：

```bash
npm start
```

2. 浏览器打开 `http://127.0.0.1:5173`（不要直接双击打开 `index.html`）。
3. 若首次使用：按引导选择 AI 服务商 → 填写密钥 →「测一下」→ 填写模型正式名称并保存。
4. 上传题目（或点「导入示例题」）→「开始生成论文」。
5. 看上方中文进度。若中断，按提示「继续任务」或「去检查模型设置」。
6. 完成后在「产物」里预览论文；需要排障时展开「高级详情」。

完整流程可能需要数十分钟到数小时。中途关闭页面后，仍可加载 `runs/ui-latest` 继续。

## 与 CLI 的对应关系

| 界面操作 | CLI / 文件 |
|----------|------------|
| 开始生成论文 | `math-agent supervise` |
| 停止 | 终止当前 worker（API `/api/runs/:id/stop`） |
| 继续任务 | `math-agent recover` |
| 通过并继续 / 驳回 | `math-agent supervise-resume` |
| 当前状态 | `math-agent status --json` + `supervisor.json` / `failure.json` |

可靠执行语义见 [`docs/beacon-resilient-execution.md`](../docs/beacon-resilient-execution.md)。

## 主要 API

- `GET /api/progress?out=&thread=`：用户态进度（`user_*`）+ `tech`
- `POST /api/attach`：附着已有输出目录
- `POST /api/runs/:id/recover`：从断点继续
- `POST /api/runs/:id/stop`：停止
- `GET /api/runs-history`：历史任务列表
- `GET /api/file?out=&name=`：安全读取产物文件（图 / PDF）

## 题面与附件

题面支持 JSON、Markdown、TXT、PDF 和 Word。数据附件支持 Excel、CSV、PDF、Word、TXT 和 Markdown，可多选上传；服务端会保存附件并生成摘要，运行时把真实文件路径写入题目配置。

## 测试

```bash
npm.cmd test -- --run
```
