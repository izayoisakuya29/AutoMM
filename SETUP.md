# AutoMM 0.0.4 配置教程

> 面向 Windows + PowerShell。从「刚 clone 仓库」走到「全部配置完成 + 拿到启动 prompt」。
> 全程不需要改任何 harness 源码；ssh密钥/题目/数据都由你手动放置。
> 本教程默认模式选择为ssh，local模式同理
---

## 0. 准备&环境说明

| 需要 | 说明 / 如何确认 |
|---|---|
| Windows + PowerShell | 本机 |
| Python 3.11+ | `python --version`（3.13 已实测） |
| uv（推荐，可选） | `uv --version`；没有也能用 `python -m venv` + `pip` |
| Node.js + npm | `node --version`（DSH / Kimi CLI 用） |
| 模型后端凭据 | DeepSeek / OpenAI / Kimi 按需，见第 2 步 |
| 一台 Linux SSH 服务器 | 可 SSH + SFTP，装好 Python 3.11+ 与 numpy/pandas/scipy/openpyxl |
| QQ 邮箱 + 授权码 | 可选，用于通知；授权码 ≠ 登录密码 |
| 题目 + 数据文件 | 仓库里**不含**真实数据，需你自备，见第 3 步 |

---

## 1. 克隆仓库

```powershell
git clone <repo-url> AutoMM
cd AutoMM
```

> 之后所有命令都在这个目录下执行（注意启动项目文件下的venv）。

---

## 2. 模型后端

AutoMM 通过 `config/agent_runtime.yaml` 的 `profiles` 选择原生 harness，默认 `deepseek`。模型族与 harness 绑定，不做协议转换；完整字段、按 Agent 覆盖和安全说明见 `LLM_PROFILES.md`。以下命令都在仓库根目录执行，并使用项目 venv 的 Python。

### 2.1 DeepSeek（DSH）

- 确认 `config/agent_runtime.yaml` 的 `deepseek.executable` 指向 DSH CLI，例如本机：
  `D:/deepseek harness/resources/runtime/cli/bin/dsh.cmd`。
- 确认 `~/.dsh/profiles/headless` 已初始化（没有时先在普通终端执行一次
  `dsh --profile headless --help`，或运行一次 `dsh web` 完成初始化）。
- 模型切换：只改 profile 的 `provider` + `model`。适配器每次动作都会生成
  `--patch` 覆盖 `agent-default-model`，不需要手改 DSH 的模型配置。
- 凭据：DSH 0.2.2 的 headless **默认禁用托管凭据存储**，只认启动环境、工作目录 `.env`
  和 `$DSH_HOME/.env`；AutoMM 会从子进程环境中移除 `DEEPSEEK_*`，因此推荐按 DSH 官方说明
  在 `~/.dsh/profiles/headless/cordis.patch.yml` 末尾恢复凭据存储：

  ```yaml
  - id: credentials
    disabled: false
  - id: authorization
    disabled: false
  - id: deepseek-account
    disabled: false
  ```

  这样 headless 会读取 `~/.dsh/.credentials.yaml` 中的 `refs.DEEPSEEK_API_KEY`，
  密钥既不需要进入仓库，也不需要写入 profile。
- 验证：

  ```powershell
  .venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile deepseek
  ```

  预期打印 `"returncode": 0` 和符合 schema 的 `response`。

### 2.2 OpenAI（Codex）

- 安装 Codex CLI/桌面端并完成 ChatGPT 登录（`codex login`），或按 Codex 自己的方式配置 API key。
- `config/agent_runtime.yaml` 保持 `executable: auto`：AutoMM 依次查找 PATH 上的 `codex`、
  `C:\Program Files\WindowsApps\OpenAI.Codex_*\app\resources\codex.exe`，无法枚举
  WindowsApps 时回退到当前用户 AppX 注册表（按版本取最新）。
- `CODEX_HOME` 默认 `~/.codex`；ChatGPT 登录态和 Codex 配置都留在该目录，AutoMM 不读取、不复制。
- 适配器用 `--output-schema` 强制结构化 JSON，并用 `--output-last-message` 把最终消息写入
  `runtime/actions/<action_id>/response.json`。当前 profile 为完全 bypass
  （`--dangerously-bypass-approvals-and-sandbox`），**风险自负**；需要审批时把
  `bypass_approvals` 改为 `false` 并配置 `sandbox`。
- 网络：Codex 需要能访问 ChatGPT 后端。若 smoke 报 `workspace routing discovery timed out`
  或 MCP transport 错误，先检查代理/VPN、`chatgpt.com` 连通性和 Codex 的 MCP server 配置。
- 验证：

  ```powershell
  .venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile openai
  ```

### 2.3 Kimi（Kimi Code）

- 在项目内安装官方 CLI（Node >= 22.19）：

  ```powershell
  cd tools\kimi-cli
  npm install --omit=dev --no-audit --no-fund
  node node_modules/@moonshot-ai/kimi-code/dist/main.mjs --version
  cd ..\..
  ```

  预期最后一条命令打印 `2.6.3`。profile 通过 `node` +
  `tools/kimi-cli/node_modules/@moonshot-ai/kimi-code/dist/main.mjs` 调用，避免 `.cmd`
  对含引号/换行 prompt 的二次解析。

- API key：设置 `KIMI_API_KEY` 环境变量，或让 profile 的 `api_key_file` 指向一个 JSON 文件
  （格式 `{"apiKey":"..."}`）。不要把 key 写进 `config/agent_runtime.yaml` 或提交到仓库。
- `config_file` 与 seed：适配器会把 `config_file` 复制为
  `runtime/kimi-code-home/config.toml`（目标已存在时不覆盖）。`model` 必须是该
  `config.toml` 中 `[models.*]` 定义的别名；Kimi 桌面端 Daimon 分享配置通常没有 `kimi-code`，
  本机验收使用 K3.1 Pro 别名 **`k3d1-agent`**（源 config 的 `default_model` 仍是 `k3-agent`，
  profile 的 `-m` 会覆盖）。换 config 时按实际别名修改 profile。
- 上下文：K3.1 Pro 的 `[models.k3d1-agent] max_context_size` 当前为 `1000000`；源 config 和
  seed 后的 `runtime/kimi-code-home/config.toml` 都已更新。1M（XL）上下文可能需要相应会员等级。
- Windows Git Bash：若 CLI 报找不到 bash，在 profile 的 `extra_env` 增加：

  ```yaml
  extra_env:
    KIMI_SHELL_PATH: "C:/Program Files/Git/bin/bash.exe"
  ```

- 验证：

  ```powershell
  .venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile kimi
  ```

  smoke 脚本已强制 UTF-8 输出；如果其他打印模型输出的工具仍遇到 GBK 编码错误，
  可执行 `$env:PYTHONIOENCODING = "utf-8"` 再重跑。

### 2.4 三个 profile 的往返验证

依次运行（每次会消耗少量模型额度）：

```powershell
.venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile deepseek
.venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile openai
.venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile kimi
```

每个命令都应在 stdout 打印 `"returncode": 0` 和符合 `config/agent_response.schema.json` 的
`response`。失败时脚本会打印含 `error`、`returncode` 和 `stderr_tail` 的 JSON，不会伪造成功；
按 `LLM_PROFILES.md` 的对应 harness 章节排查。

---

## 3. 放置题目与数据

仓库按 provenance 约定不含真实比赛数据，需要你手动放入：（以2023年国赛C题为例）

```text
request/problem.md                  # 题面
request/attachments/C题.pdf         # 官方附件
data/附件1.xlsx                     # 数据
data/附件2.xlsx                     # 数据
data/附件3/result1_1.xlsx           # 提交模板
data/附件3/result1_2.xlsx           # 提交模板
data/附件3/result2.xlsx             # 提交模板
```

---

## 4. 创建 Python venv 并装依赖

用 uv（速度较快）：

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r scripts\requirements.txt
```

不用 uv：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scripts\requirements.txt
```

激活成功后命令行前缀会变成 `(.venv)`。验证：

```powershell
python -c "import numpy, pandas, scipy, paramiko, jsonschema, psutil; print('deps ok')"
```

> 注意：之后所有 harness 命令都必须用 venv 的 python（激活后直接 `python`，或用
> `.\.venv\Scripts\python.exe`）。用系统 python 会报 `ModuleNotFoundError`。

---

## 5. 一键配置：SSH + 邮箱 + 计算模式

```powershell
python scripts\configure_remote.py
```

脚本会**在开头先让你选计算模式**：

```text
请先选择计算模式：
  local  —— 所有计算在本地跑（本地压力大）
  remote —— 重计算走远端 SSH，本地只做编排 + 轻量 smoke（推荐用于全量）
计算模式 (local/remote) [local]:
```

- 选 `remote` → 接着填 SSH（host/端口/用户名/密码/远端目录），`default_backend` 自动写 `ssh`。
- 选 `local` → 跳过 SSH，`default_backend` 写 `local`。

接着填 QQ 邮箱（SMTP/IMAP/授权码/收发件人/allowed_senders），最后它会问是否探测连接。
> 本项目强制依赖qq邮箱异步确认，所以强烈建议新建一个qq邮箱账号用来发送通知并接受指令。

**只读查看当前配置** ：

```powershell
python scripts\configure_remote.py show
```

> 脚本只写三个 config（`ssh.yaml` / `notifications.yaml` / `compute.yaml`），写前自动备份，
> 不碰任何 `scripts/automm` 逻辑。可反复运行（当前值作为默认）。

### 5.1 邮箱配置

```yaml
smtp_host: smtp.qq.com      
imap_host: imap.qq.com      
password: "<16位授权码>"     # 授权码，不是 QQ 登录密码，具体可以在qq邮箱网页端-设置-账号与安全-安全设置中，找到POP3/IMAP/SMTP/Exchange/CardDAV 服务开启后自行配置
```

---

## 6. 初始化题目

```powershell
python scripts\harness.py init-problem --problem-id <你自己的具体题目> --questions <题目的具体小问数量>
```

预期输出 `problems/题目名称`，并在其下生成 `probxx`。

---

## 7. 逐项顺序自检

```powershell
# 1) 配置校验
python scripts\harness.py validate-config

# 2) SSH 连通 + 远端 Python
python scripts\sync_remote.py --backend ssh probe

# 3) 发一封测试邮件
python scripts\notify_email.py send --kind problem-complete --message "AutoMM 测试邮件"

# 4) 收件测试（会读收件箱，旧控制邮件可能被当作 PAUSE/RESUME 执行，属正常）
python scripts\notify_email.py poll

# 5) 模型往返（已在第 2 步验证过）
```

预期：① 全 `PASS`；② `"status": "ok"` 且 `host_key_sha256` 与配置一致；③ 打印含 `request_id` 的 JSON；④ 打印消息列表。

---

## 8. 启动harness

先单步跑一个动作，确认所选模型后端（默认 DSH headless）真实调用 OK：

```powershell
python scripts\orchestrator_runner.py
```

无报错后，后台持续推进（或 `--once` 逐步）：

```powershell
python scripts\orchestrator_daemon.py
```

然后把文末「附」的**标准化 prompt** 开新 session 贴进去，让它做「调度 + 监控 + 汇报」。

---

## 9. 启动实时 Dashboard（只读监测台，强烈推荐）

full smoke 跑起来后，**另开一个终端**起 dashboard，实时看状态/任务/事件/日志，不用反复敲命令查：

```powershell
.\.venv\Scripts\Activate.ps1
python monitor\monitor.py
```

看到 `AutoMM monitor running at http://127.0.0.1:8765` 后，浏览器打开 **http://127.0.0.1:8765** 即可。

要点：
- **只读、独立进程**：不写文件、不抢锁、不 import automm，可随时启停（Ctrl+C），不影响正在跑的 harness。
- **监测哪个目录**：读它自己所在的目录；想从别处指向另一份 harness，先 `$env:AUTOMM_ROOT = "<目标目录>"` 再启动。
- 页面功能：运行状态徽标、小问/阶段两个滚动窗口、资产树 + markdown/公式查看器、TASKS/EVENTS/DAEMON LOG 三栏。

---
## 附：启动 harness 的标准化 Prompt

```text
你是 AutoMM 全自动数学建模 harness 的调度操作员，负责把一次真实数模竞赛题目完整跑通并汇报结果。

## 一、本次题目（每轮替换此段即可复用）
- 竞赛：2024 高教社杯全国大学生数学建模竞赛 C 题「农作物的种植策略」。
- problem_id：crop_2024；共 3 个小问（prob01/prob02/prob03）。
- 题面：request/problem.md；附件：request/attachments/C题.pdf。
- 数据：data/附件1.xlsx、data/附件2.xlsx、data/附件3/result1_1.xlsx、result1_2.xlsx、result2.xlsx。

## 二、环境与前置状态
- 工作目录：本仓库根目录（用 venv 的 python：.\.venv\Scripts\python.exe）。
- 已配置：模型后端=default_profile(deepseek/DSH)，可按 Agent 覆盖；计算=remote SSH；邮件=QQ；default_backend=ssh。
- 当前：active_problem=crop_2024，current_stage=problem_understanding。

## 三、角色与硬约束
1. 只做「调度 + 监控 + 汇报」，不亲自做建模判断。
2. 绝不直接编辑 runtime/workflow_state.json 或小问 manifest 门禁字段；状态变更只能经 harness commands。
3. 计算必须走隔离 task 且 backend=ssh（本地不跑完整 computation）。
4. 失败按 failure_class 路由：agent_transport/infrastructure_transient→重试；code_runtime→修订；harness_invariant→严格失败并上报；仅凭据/远端不可用/输入缺失才允许人工阻塞。
5. 不覆盖假设、公式、结果、日志、结论历史。

## 四、启动与推进
1. 单步验证：python scripts\orchestrator_runner.py
2. 持续推进：python scripts\orchestrator_daemon.py（或 --once 逐步）

## 五、监控要点
- 阶段：Get-Content runtime\workflow_state.json
- 可读状态：Get-Content reports\autoresearch\STATE.md
- 任务：python scripts\compute_dispatcher.py list --json
- 远端：python scripts\sync_remote.py --backend ssh status --task-id <task_id>
- 日志：Get-Content runtime\daemon\daemon.log -Tail 30
- 动作证据：runtime\actions\<action_id>\

## 六、结束与交付
- 结束条件：current_stage=completed 且 3 小问都过 sanity + 跨小问审查，或 daemon 进入 blocked/idle。
- 汇报：① 每题结论与 result1_1/result1_2/result2.xlsx 路径；② 各阶段 sanity 结论；③ 失败/降级及原因；④ 全程耗时。
- blocked 处置规程（遇到 recovery_status=human_blocked 时）
1. 定位：读 runtime/actions/<action_id>/stdout.log，grep "action_id"，
   比对 Agent 返回的 action_id 与预期 action_id。
2. 若是「action_id 幻觉」（返回了形如 act-cqr-xxx 的自造 ID，且 problem_id/question_id 正确）
   → 复位后继续：
     - python 改 workflow_state.json：recovery_status="normal"、failure_class=null、
       blocking=[]、recovery 重置；
     - 写 runtime/flags/pending_wakeup.flag 唤醒 daemon。
3. 若是「真 harness_invariant」（schema 校验失败 / problem_id 不匹配 / 命令批回滚）则不做变化

## 七、本次属于 full_smoke
- 首次端到端实跑，目标是暴露并修复问题；报错优先带回「阶段 + failure_class + 日志」，不要反复重试同一命令。
```
