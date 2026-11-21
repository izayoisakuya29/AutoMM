# AutoMM 原生多 Harness 解耦设计

日期：2026-11-18
状态：已审阅（2026-11-18）
基线：AutoMM 0.0.4-dsh（上游 main，d0d97fd）

## 1. 背景

AutoMM 的编排层（workflow 状态机、事务、task 隔离、sanity、可视化、通知、SSH 计算）与模型调用层已经分离。`scripts/automm/llm/` 提供了 `LLMProvider` 抽象，`agent_runtime.py` 只通过 `prepare()` 和 `extract_response()` 接触后端。

但 0.0.4-dsh 仍有三处绑定 DSH：

- `config/agent_runtime.yaml` 默认 `provider: dsh_headless`，文档要求安装 DSH 和 DeepSeek 凭据。
- DSH headless 0.1.1 没有 `--model`，模型选择被交给 `$DSH_HOME/settings.yaml`。
- `DSH_TOOLS_MODE` 和 `AGENTS.md` 加载依赖 DSH profile。

用户要求 AutoMM 继续负责全部工程指导与操作步骤，但 harness 与模型可以按 Agent 灵活搭配，且不同模型族必须使用各自的原生 harness：

- DeepSeek：DeepSeek Harness（DSH）
- OpenAI：Codex CLI
- Kimi：Kimi Code 官方 CLI
- openJiuwen：保留扩展点，本阶段不实现
- 不做 Anthropic 兼容网关等协议转换，避免工程能力下降

## 2. 目标与非目标

### 目标

- AutoMM 编排逻辑不变，模型调用改为可配置的 profile。
- 每个 profile 绑定一个原生 harness 和一个模型；Agent 可单独覆盖 profile。
- 支持三种原生 harness 适配器：
  - `dsh_headless`：DeepSeek，模型通过 `--patch` 覆盖。
  - `codex_exec`：OpenAI，沿用现有 `codex exec` 适配器并升级。
  - `kimi_code`：Kimi Code 官方 CLI，新增适配器。
- DSH 和 Codex 的 prompt 通过 stdin 投递；Kimi Code 官方 CLI 使用 `-p`，适配器设置 30000 字符上限保护。
- 响应解析、jsonschema、`action_id`、commands 白名单、事务和回滚逻辑保持不变。
- 配置、测试、文档、smoke 脚本一并更新。
- 仓库重新落地到 `H:\数学建模竞赛\数学建模项目\逆向全自动数模`。

### 非目标

- 不改造数学建模工作流为逆向工作流；REA/逆向适配是下一阶段。
- 不实现直接模型 API provider，也不自建带工具循环的 agent runtime。
- 不实现 openJiuwen 适配器；只保留工厂名称和配置扩展点。
- 不把 Claude Code 纳入默认 harness。
- 不实现 OpenAI/DeepSeek/Kimi 之间的协议转换或跨模型族回退。
- 不修改 `scripts/automm` 中与模型调用无关的状态机、任务和门禁逻辑。

## 3. 成功标准

- `python scripts/harness.py validate-config` 全部 PASS。
- `python -m compileall -q scripts tests` 通过。
- 现有测试套件通过；新增单元测试和假 harness 集成测试通过。
- 对三个 profile 手动运行真实 smoke，均返回符合 `config/agent_response.schema.json` 的 JSON：
  - `deepseek`：DSH + DeepSeek V4
  - `openai`：Codex + GPT
  - `kimi`：Kimi Code CLI + Kimi Code
- 只改配置即可切换 harness/模型；按 Agent 覆盖生效，并在 `runtime/actions/<action_id>/status.json` 中记录实际 profile、harness 和模型。
- 仓库和日志中不出现 API key。

## 4. 架构

组件：

- `config/agent_runtime.yaml`：全局运行配置、默认 profile、profile 定义、超时和输出 schema。
- `config/agent_registry.yaml`：Agent 提示词、阶段和可选的 profile 覆盖。
- `scripts/automm/llm/profiles.py`：加载配置、按 Agent 解析 profile、校验可用性。
- `scripts/automm/llm/base.py`：`Invocation`、`LLMProvider`、`ProviderError`、`ProviderConfigError`、`ProviderAuthError`。
- `scripts/automm/llm/dsh.py`：DSH 适配器。
- `scripts/automm/llm/codex.py`：Codex 适配器。
- `scripts/automm/llm/kimi.py`：Kimi Code 适配器。
- `scripts/automm/llm/__init__.py`：harness 工厂和注册表；`openjiuwen` 名称保留。
- `scripts/automm/agent_runtime.py`：解析 profile、调用适配器、校验响应、记录元数据。
- `scripts/automm/failure_policy.py`：新增配置/认证错误的分类。
- `scripts/harness.py`：扩展 `validate-config`。
- `scripts/smoke_llm_roundtrip.py`：真实模型往返 smoke。

数据流：

1. Runner 决定 `run_agent` 动作。
2. `invoke_agent(agent, action, action_id)` 读取 `agent_runtime.yaml` 和 `agent_registry.yaml`，解析 profile。
3. 工厂按 `harness` 创建适配器。
4. 适配器 `prepare()` 生成命令、stdin、环境、输出路径和元数据。
5. `subprocess.Popen` 在项目根目录执行；DSH/Codex 的 prompt 走 stdin，Kimi 的 prompt 走 `-p` 参数。
6. 适配器 `extract_response()` 解析最终 JSON。
7. 原有 jsonschema、`action_id` 和上下文校验继续执行。
8. `status.json` 记录 profile、harness、模型、可执行文件、退出码和可用的成本/用量。

## 5. 配置模型

### 5.1 agent_runtime.yaml

新结构：

```yaml
enabled: true
default_profile: deepseek
profiles:
  deepseek:
    harness: dsh_headless
    executable: D:/deepseek harness/resources/runtime/cli/bin/dsh.cmd
    dsh_home: ~/.dsh
    dsh_profile: headless
    provider: deepseek-official
    model: deepseek-v4-pro
    permission_mode: workspace-write
    approval_policy: never
    timeout_seconds: 2400
  openai:
    harness: codex_exec
    executable: auto
    codex_home: ~/.codex
    model: gpt-6-luna
    bypass_approvals: true
    sandbox: danger-full-access
    skip_git_repo_check: true
  kimi:
    harness: kimi_code
    executable: node
    executable_args:
      - tools/kimi-cli/node_modules/@moonshot-ai/kimi-code/dist/main.mjs
    kimi_code_home: runtime/kimi-code-home
    api_key_file: C:/Users/MECHREVO/AppData/Roaming/kimi-desktop/daimon-share/daimon/kimi-code-key.json
    api_key_env: KIMI_API_KEY
    base_url: https://agent-gw.kimi.com/coding/v1
    model: kimi-code/kimi-for-coding
    max_prompt_chars: 30000
    timeout_seconds: 2400
stage_timeout_seconds:
  default: 1800
  problem_understanding: 1200
  literature_review: 2400
  assumption_definition: 1800
  mathematical_formulation: 2400
  implementation: 1800
  resource_manager: 300
  resource-manager: 300
  sanity_check: 900
  sanity-checker: 900
  visualization: 1800
  robustness: 1800
  ablation: 1800
  cross_question_review: 1800
  final_summary: 1200
  computation: 0
timeout_policy:
  action_timeout: retry_next_wake
  preserve_drafts: true
  preserve_logs: true
  second_timeout_mode: convergence
output_schema: config/agent_response.schema.json
registry: config/agent_registry.yaml
max_output_chars: 200000
capability_probe_on_start: true
```

规则：

- 旧的扁平 `provider`、`executable`、`profile`、`tools_mode`、`model`、`sandbox`、`automatic_approval`、`ephemeral`、`required_capabilities` 字段从顶层移除；对应能力下沉到 profile。
- profile 名在 `profiles` 内唯一；`default_profile` 必须存在。
- `enabled: false` 的 profile 不允许被 Agent 引用。
- 未识别的字段在 validate-config 中报错，避免拼写错误静默生效。
- profile 的 `timeout_seconds` 优先于 `stage_timeout_seconds`；未设置时沿用阶段超时。

### 5.2 agent_registry.yaml

每个 Agent 增加可选的 `profile`：

```yaml
agents:
  sanity-checker:
    prompt: agents/sanity-checker.md
    stages: [sanity_check, computation_result]
    profile: openai
  literature-researcher:
    prompt: agents/literature-researcher.md
    stages: [literature_review]
    profile: kimi
```

未指定 `profile` 时使用 `default_profile`。`profile` 指向不存在的名称或已禁用的 profile 时，validate-config 和运行时都报配置错误。

### 5.3 profile 解析优先级

1. Agent registry 的 `profile`。
2. `agent_runtime.yaml` 的 `default_profile`。

解析结果包含：profile 名、harness、模型、可执行文件、环境变量、工作目录、超时、harness 专属选项。解析结果只读；每次动作重新解析，避免切换配置后需要重启 daemon。

### 5.4 本机默认路径

- DSH CLI：`D:\deepseek harness\resources\runtime\cli\bin\dsh.cmd`，版本 0.2.2-rc.3。
- DSH home：`~/.dsh`；headless profile 目录 `~/.dsh/profiles/headless`。
- Codex home：`C:\Users\MECHREVO\.codex`，包含 `config.toml`、`auth.json`、会话和插件。
- Codex 可执行文件：优先 PATH 上的 `codex`，否则自动发现
  `C:\Program Files\WindowsApps\OpenAI.Codex_*\app\resources\codex.exe`。
- Kimi CLI：项目内 `tools/kimi-cli` 安装 `@moonshot-ai/kimi-code@2.6.3`；通过 `node tools/kimi-cli/node_modules/@moonshot-ai/kimi-code/dist/main.mjs` 调用，避免 `.cmd` 对含引号/换行 prompt 的解析问题。
- Kimi Code 密钥：`%APPDATA%\kimi-desktop\daimon-share\daimon\kimi-code-key.json` 的 `apiKey` 字段，或环境变量 `KIMI_API_KEY`。
- Kimi Code home：项目内 `runtime/kimi-code-home`，由适配器创建。
- openJiuwen：未安装；仅在工厂注册名称。

## 6. Harness 适配器契约

### 6.1 通用接口

沿用 `LLMProvider`：

```python
class LLMProvider(ABC):
    backend: str
    def probe(self) -> dict[str, Any]: ...
    def prepare(self, prompt: str, output_path: Path) -> Invocation: ...
    def extract_response(self, invocation, stdout, stderr, returncode) -> dict[str, Any]: ...
```

`Invocation` 扩展为：

```python
@dataclass
class Invocation:
    command: list[str]
    stdin: str | None = None
    env: dict[str, str] | None = None
    output_path: Path | None = None
    meta: dict[str, Any] | None = None
```

`meta` 记录 profile、harness、模型、可执行文件、patch 路径、是否 bypass 等，不含密钥。

适配器构造函数接收解析后的 profile 字典和项目根目录；不再直接读 `agent_runtime.yaml`。profile 可提供 `executable_args`，适配器把 `[executable, *executable_args]` 作为命令前缀，Kimi 用它在 Node 下直接运行 `main.mjs`。

### 6.2 DSH 适配器

可执行文件：

- 来自 profile 的 `executable`；必须存在。
- `dsh_home` 展开 `~` 后必须存在，且包含 `profiles/<dsh_profile>`。
- 调用 `.cmd` 时使用绝对路径；若 Python `subprocess` 无法直接执行，使用 `cmd.exe /d /c` 包装。

命令：

```text
dsh.cmd --profile headless --patch <patch_path> --permission-mode <mode> --approval-policy <policy> -
```

- 任务参数 `-` 表示从 stdin 读；`stdin` 为完整 prompt。
- `--patch` 为每次动作生成的临时 YAML 文件，路径在 `runtime/actions/<action_id>/dsh_patch.yml`。
- `--permission-mode` 和 `--approval-policy` 来自 profile；默认 `workspace-write` 和 `never`。
- 可选 `--add-dir` 通过 profile 的 `extra_args` 追加。

patch 内容：

```yaml
- id: agent-default-model
  config:
    provider: deepseek-official
    model: deepseek-v4-pro
```

- DSH 的 patch 是整体替换 `agent-default-model` 配置，`provider` 必须与 `model` 一起写。
- profile 可通过 `patch_config` 追加其他字段，例如 `reasoningEffort`。
- 适配器始终写临时 patch，不修改 `~/.dsh/profiles/headless/cordis.patch.yml`。

输出：

- stdout 为最终 assistant 文本；stderr 为诊断和推理过程。
- `extract_response` 只在 stdout 上解析 JSON，沿用 `_parse_json_text` 的围栏和区间提取。
- 退出码非零时抛 `AgentTransportError`，错误信息取 stderr 尾部。

探测：

- `dsh.cmd --version`。
- 检查 `dsh_home/profiles/<dsh_profile>` 存在。
- 不执行模型调用。

### 6.3 Codex 适配器

可执行文件解析顺序：

1. profile 的 `executable`，若不是 `auto`。
2. `shutil.which("codex")`。
3. 匹配 `C:\Program Files\WindowsApps\OpenAI.Codex_*\app\resources\codex.exe`，按版本目录排序取最新。
4. 都找不到则抛 `ProviderConfigError`。

环境：

- `CODEX_HOME` 展开 `~`，默认 `~/.codex`。
- 沿用 Codex 自己的 ChatGPT OAuth 或 API key 配置；AutoMM 不读取、不复制 Codex 凭据。

命令：

```text
codex.exe exec - -C <ROOT>
  --output-schema <schema_path>
  --output-last-message <run_dir>/response.json
  --json --color never
  --skip-git-repo-check
  --model <model>
  [-p <config_profile>]
  [--dangerously-bypass-approvals-and-sandbox | --sandbox <mode> --approve-for-me]
  [extra_args]
```

- prompt 通过 stdin 传入，`-` 表示从 stdin 读。
- `bypass_approvals: true` 时使用 `--dangerously-bypass-approvals-and-sandbox`；否则使用 `--sandbox <sandbox>` 和 `--approve-for-me`。`sandbox` 只在非 bypass 模式生效。
- `config_profile` 非空时追加 `-p <name>`，使用 `$CODEX_HOME/<name>.config.toml`。
- `output_path` 为 `runtime/actions/<action_id>/response.json`；适配器从该文件读最终 JSON。
- `--json` 事件写入 stdout，作为原始日志保留，不参与响应解析。

探测：

- `codex --version`。
- `codex exec --help` 检查 `--output-schema`、`--output-last-message`、`--skip-git-repo-check`、`--json`、`--sandbox`、`--approve-for-me`、`--cd` 是否存在。
- 不执行模型调用。

### 6.4 Kimi Code 适配器

安装：

- 在项目内 `tools/kimi-cli` 创建独立 npm 包，安装 `@moonshot-ai/kimi-code@2.6.3`。
- 通过 Node 直接运行 `tools/kimi-cli/node_modules/@moonshot-ai/kimi-code/dist/main.mjs`，不经过 `.cmd`，避免 Windows `cmd.exe` 对含引号、换行 prompt 的二次解析。
- profile 使用 `executable: node` 和 `executable_args: [<main.mjs>]`；适配器把它们放在 harness 参数之前。
- 在 `.gitignore` 增加 `tools/kimi-cli/node_modules/`。

环境：

- `KIMI_CODE_HOME` 指向项目内 `runtime/kimi-code-home`，适配器在调用前创建。
- API key 读取顺序：
  1. profile 的 `api_key_env` 对应的环境变量。
  2. profile 的 `api_key_file`，读取 JSON 的 `apiKey` 字段。
- 设置 `KIMI_API_KEY`；设置 `KIMI_CODE_BASE_URL`（若 profile 提供）。
- 不把 key 写入日志、`status.json` 或项目配置。

命令：

```text
node <main.mjs> -m <model> -p <prompt> --output-format text [extra_args]
```

- Kimi Code 官方 CLI 的文档化非交互入口是 `-p/--prompt <prompt>`；prompt 作为参数传入。
- profile 的 `max_prompt_chars` 默认 30000；prompt 超过上限时抛 `ProviderConfigError`，不做静默截断。AutoMM 的 Agent prompt 预计在 10000 字符量级，远低于上限。
- `-p` 不能与 `--yolo`、`--auto`、`--plan` 同时使用；非交互模式使用 Kimi Code 的自动权限。
- `-m/--model` 来自 profile，默认 `kimi-code/kimi-for-coding`。
- `--output-format text` 输出最终 assistant 文本；不使用未在官方参考页确认的 `--quiet` 或 `--final-message-only`。
- profile 可通过 `extra_args` 追加其他已确认的参数。
- Windows 上 Kimi Code CLI 依赖 Git Bash；若自动探测失败，profile 的 `env` 设置 `KIMI_SHELL_PATH` 为 `bash.exe` 的绝对路径。

输出：

- stdout 最终 assistant 文本；stderr 为思考和工具过程。
- `extract_response` 在 stdout 上解析 JSON。
- 退出码 75 视为可重试，抛 `AgentTransportError`；其他非零退出码按 stderr 内容分类，认证错误抛 `ProviderAuthError`。

探测：

- `node <main.mjs> --version`。
- `node <main.mjs> --help` 检查 `-m/--model`、`-p/--prompt`、`--output-format` 存在。
- 不执行模型调用。

### 6.5 openJiuwen 扩展点

- 工厂注册表包含 `openjiuwen` 名称。
- 选择 `harness: openjiuwen` 时抛 `ProviderConfigError("openjiuwen harness 本阶段仅保留扩展点，尚未实现")`。
- 不安装 `openjiuwen` Python 包，不导入其模块。
- `LLM_PROFILES.md` 提供注释掉的示例 profile 和新增适配器需要实现的接口。
- 后续实现时新增 `scripts/automm/llm/openjiuwen.py` 并在工厂注册，不改动 `agent_runtime.py`。

## 7. 运行时行为

### 7.1 prompt 投递

- DSH 和 Codex 使用 stdin；`Invocation.stdin` 为完整 prompt，任务参数为 `-`。
- Kimi 使用文档化的 `-p <prompt>`；适配器在超过 `max_prompt_chars` 时抛配置错误，不做截断。
- DSH 和 Codex 不再把 agent 指令、action JSON 或项目规则拼进命令行；Kimi 的 `-p` 参数就是完整 prompt。

### 7.2 输出解析

- DSH、Kimi：解析 stdout 文本。
- Codex：读取 `--output-last-message` 指定的文件；文件缺失时抛 `AgentTransportError`。
- 共用 `_parse_json_text`：先去除 ANSI 转义序列，再剥 ```json 围栏，取第一个 `{` 到最后一个 `}`，`json.loads`。
- 解析结果继续经过 `jsonschema.validate`、`action_id` 校验、`problem_id`/`question_id` 上下文校验和 commands 白名单校验。

### 7.3 环境构造

- 基础环境保留 PATH、HOME、USERPROFILE、TEMP、TMP、SystemRoot、COMSPEC、PATHEXT 等运行必需变量。
- 移除当前会话可能泄漏的 provider 变量：`ANTHROPIC_*`、`CLAUDECODE`、`CLAUDE_*`、`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`。
- 各适配器只注入自己需要的变量：
  - DSH：`DSH_HOME`。
  - Codex：`CODEX_HOME`。
  - Kimi：`KIMI_CODE_HOME`、`KIMI_API_KEY`、`KIMI_CODE_BASE_URL`。
- profile 的 `extra_env` 可追加非敏感变量；禁止把密钥写入配置文件。
- 不继承 `CLAUDE_APP_ROOT`、`CLAUDE_CODE_*` 等宿主会话变量。

### 7.4 日志与元数据

- `runtime/actions/<action_id>/status.json` 增加：
  - `profile`
  - `harness`
  - `model`
  - `executable`
  - `returncode`
  - `session_id`（若适配器能提供）
  - `cost_usd`、`usage`（若适配器能提供）
- `invoke_agent` 返回的 `meta` 同步包含上述字段。
- stdout/stderr 继续写入 `stdout.log`/`stderr.log`；Codex 的 `--json` 事件在 stdout。
- 不记录 API key、Authorization 头或完整环境变量。

### 7.5 超时

- 沿用 `stage_timeout_seconds` 和 `_terminate_process_tree`。
- profile 的 `timeout_seconds` 优先；`0` 表示不设超时（与现有语义一致）。
- 超时后保存 stdout/stderr，写 `status.json`，抛 `AgentTimeoutError`，由 Runner 走重试。

### 7.6 错误分类

新增异常：

- `ProviderConfigError`：profile 不合法、可执行文件缺失、DSH profile 不存在、Kimi 密钥缺失、openJiuwen 未实现。
- `ProviderAuthError`：CLI 明确报告 401/403/认证失败。

分类：

- `ProviderConfigError`、`ProviderAuthError` → `external_human_required`，进入人工阻塞。
- `AgentTransportError`、可重试退出码（Kimi 75）、进程启动失败 → `agent_transport`，重试。
- 无效 JSON → `AgentTransportError`，重试。
- schema 校验失败、action_id 不匹配、上下文不匹配 → 保持现有语义（action_id 不匹配仍按瞬时传输错误重试；schema/上下文按 harness invariant）。
- 超时 → 现有 `AgentTimeoutError` 路径。

`failure_policy.classify_exception` 增加对新异常类型的识别；`agent_runtime` 不再把所有 provider 错误一律包装成 `AgentTransportError`。

## 8. 配置校验

`scripts/harness.py validate-config` 增加：

- `agent_runtime.yaml` 必须包含 `default_profile` 和 `profiles`。
- `default_profile` 存在且未禁用。
- 每个 profile 的 `harness` 在 `{dsh_headless, codex_exec, kimi_code, openjiuwen}` 中。
- `openjiuwen` 若被启用，直接 FAIL，提示本阶段未实现。
- DSH profile：`executable` 存在；`dsh_home` 存在；`dsh_profile` 目录存在；`provider` 和 `model` 非空。
- Codex profile：可执行文件可解析；`model` 非空；若未 bypass，`sandbox` 合法。
- Kimi profile：`executable` 和 `executable_args` 中的 `main.mjs` 存在；`api_key_file` 或 `api_key_env` 至少一个；`model` 非空；`max_prompt_chars` 为正整数；`kimi_code_home` 的父目录可写。
- Agent registry 中每个 `profile` 引用存在且未禁用。
- 未知 profile 字段报错。
- 不读取或打印密钥值；只检查文件存在性和环境变量是否设置（未设置给警告，运行时缺失才人工阻塞）。

## 9. 测试策略

### 9.1 单元测试

- profile 解析：默认 profile、按 Agent 覆盖、禁用 profile、未知 harness、未知字段。
- DSH：命令构造、stdin、patch YAML 内容、权限参数、stdout 解析。
- Codex：可执行文件发现（mock `shutil.which` 和 glob）、命令参数、bypass 与 sandbox 互斥、输出文件解析。
- Kimi：命令参数、环境变量、密钥文件读取、prompt 长度上限、stdout 解析、退出码 75 分类。
- openJiuwen：选择时抛出明确的 `ProviderConfigError`。
- 错误分类：配置、认证、传输、schema、超时。

### 9.2 无 token 集成测试

- 用假 harness 可执行文件（`.cmd` 包装 Python 脚本）走完 `invoke_agent`：
  - DSH/Codex 读取 stdin prompt；Kimi 校验 `-p` 参数和长度上限。
  - 输出固定 JSON。
  - 验证 `action_id`、`problem_id`、`question_id`。
  - 验证 `status.json` 的 profile/harness/model 元数据。
- 按 Agent 覆盖：两个 Agent 使用不同 profile，断言命令和环境不同。
- 现有 `test_agent_runtime.py`、`test_dsh_provider_smoke.py` 按新配置更新。

### 9.3 真实往返 smoke

新增 `scripts/smoke_llm_roundtrip.py`：

- 参数：`--profile deepseek|openai|kimi`。
- 发送最小 prompt：要求只输出一个符合 `config/agent_response.schema.json` 的 JSON 对象。
- 打印 profile、harness、模型、退出码、耗时和解析结果；不打印密钥。
- 只手动运行，消耗少量 token。
- 三个 profile 都通过才视为验收完成。

### 9.4 回归

- `python -m compileall -q scripts tests`
- `pytest`
- `python scripts/harness.py validate-config`
- 现有工作流、事务、tasks、sanity 测试全部通过。

## 10. 文档更新

- 新增 `LLM_PROFILES.md`：
  - profile schema 和字段说明。
  - 三个原生 harness 的配置示例。
  - 按 Agent 覆盖示例。
  - openJiuwen 扩展点说明。
  - 安全说明：密钥来源、日志脱敏、bypass 风险。
  - 明确“不做协议转换，模型族与 harness 绑定”。
- 更新 `README.md`：
  - 去掉“必须基于 dsh 生态”的表述。
  - 说明默认 `deepseek` profile、三套原生 harness、按 Agent 覆盖。
- 更新 `SETUP.md`：
  - DSH CLI 路径与 `DSH_HOME`。
  - Codex 安装/登录与 `CODEX_HOME`。
  - Kimi Code CLI 项目内安装与密钥配置。
  - 三个 smoke 命令。
- `DSH_MIGRATION.md` 标注为历史文档，说明 0.2.2 的 `--patch`、stdin 和 `--permission-mode` 差异。
- `.gitignore` 增加 `tools/kimi-cli/node_modules/`。

## 11. 实施顺序

1. 仓库落地：从上游 tarball 解压到当前目录，`git init`，设置 `origin` 为 `https://github.com/sghwr/AutoMM.git`。
2. 创建 `.venv`，安装 `scripts/requirements.txt`。
3. 在 `tools/kimi-cli` 安装 `@moonshot-ai/kimi-code@2.6.3`，加入 `.gitignore`；使用 fnm 管理的 Node 24.22.1，若 npm 报 fnm 环境错误，先在 shell 中执行 `eval "$(fnm env)"`。
4. 实现 `llm/profiles.py` 和新的配置结构。
5. 实现 DSH、Codex、Kimi 适配器和工厂；保留 openJiuwen 扩展点。
6. 改造 `agent_runtime.py`、`failure_policy.py`、`harness.py`。
7. 更新和新增测试；用假 harness 跑通全链路。
8. 更新配置、文档和 `.gitignore`。
9. 创建并运行 smoke 脚本，依次验证 deepseek、openai、kimi。
10. 运行完整测试和 validate-config，整理变更说明。

## 12. 风险与限制

- 原生 CLI 契约可能随版本变化。已验证版本：DSH 0.2.2-rc.3、Codex 0.169.0-alpha.11.1、Kimi Code CLI 2.6.3；文档记录版本，probe 检查必需 flag。
- Codex 的 WindowsApps 可执行文件路径随应用更新变化；自动发现按版本目录选择最新，找不到时报配置错误。
- Kimi CLI 的模型别名和 API key 认证方式需要在安装后用 smoke 确认；默认别名 `kimi-code/kimi-for-coding` 来自官方示例，若不可用，按 `kimi` 模型列表返回的 Kimi Code 别名修改 profile。Windows 上若 CLI 找不到 Git Bash，需在 profile 的 `env` 中设置 `KIMI_SHELL_PATH`。
- DSH 的 `agent-default-model` patch 是整体替换；适配器始终同时写 `provider` 和 `model`。
- 完整 bypass 权限有风险；只在项目目录内无人值守运行，文档明确提示。
- openJiuwen 本阶段只有扩展点，没有真实调用。
- 不做协议转换，因此不能把某个模型族的请求回退到另一族的 harness；跨族切换必须换 profile。
- 真实 smoke 消耗 token，只在手动验收时运行。
- 仓库通过 tarball 落地而不是 `git clone`（git 传输被代理阻断）；本地 git 初始化和远端配置仍需保留，后续可重新 fetch。

## 13. 验收标准

- `validate-config` 对三个启用 profile 全部 PASS，且能指出缺失的可执行文件/密钥。
- 单元测试、无 token 集成测试、现有回归测试全部通过。
- 三个真实 smoke 全部返回 schema 合法 JSON，并在 `status.json` 记录正确的 harness/model。
- 按 Agent 覆盖 profile 的测试通过。
- `git grep` 和日志检查不出现 `sk-` 开头的密钥。
- 工作流状态机、事务、task 隔离和门禁行为无变化。

## 14. 附录：已核实的 CLI 契约

DSH 0.2.2-rc.3：

- `dsh --profile headless [options] [task...]`。
- `task` 为 `-` 时从 stdin 读。
- `--patch <path>` 在 profile 层之后叠加。
- `--permission-mode <preset>`、`--approval-policy ask|never`。
- stdout 最终答案，stderr 诊断；非零退出表示失败。

Codex 0.169.0-alpha.11.1：

- `codex exec [OPTIONS] [PROMPT]`；`PROMPT` 为 `-` 时从 stdin 读。
- `-m/--model`、`-C/--cd`、`-s/--sandbox`、`--approve-for-me`、`--dangerously-bypass-approvals-and-sandbox`。
- `--output-schema <FILE>`、`-o/--output-last-message <FILE>`、`--json`、`--color`、`--skip-git-repo-check`。
- `-p/--profile` 加载 `$CODEX_HOME/<name>.config.toml`。

Kimi Code CLI 2.6.3：

- npm 包 `@moonshot-ai/kimi-code`，bin 为 `kimi`（`dist/main.mjs`），要求 Node >= 22.19。
- 通过 `node dist/main.mjs` 调用；`-m/--model <model>`、`-p/--prompt <prompt>`、`--output-format text|stream-json`。
- `-p` 不能与 `--yolo`、`--auto`、`--plan` 同时使用；非交互模式使用自动权限。
- stdout 最终 assistant 文本，stderr 思考/工具过程。
- 退出码 0 成功、1 不可重试失败、75 可重试失败。
- 未在官方参考页确认的 `--quiet`、`--final-message-only`、`--thinking` 不作为适配器契约。
- `$KIMI_CODE_HOME` 数据目录（默认 `~/.kimi-code`）。
- 项目 `AGENTS.md` 和 `.kimi-code/AGENTS.md` 自动加载；`.kimi-code/mcp.json` 支持项目级 MCP。

openJiuwen：

- 未安装；`pip install openjiuwen` 是 Python SDK，不是本阶段依赖。
- 工厂仅保留名称，调用时返回明确的未实现错误。
