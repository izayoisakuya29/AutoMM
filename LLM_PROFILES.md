# LLM Profiles：原生多 Harness 模型后端

AutoMM 的编排层（状态机、事务、task 隔离、sanity、可视化、通知、SSH 计算）与模型调用层完全解耦。模型调用由 `config/agent_runtime.yaml` 中的 **profile** 描述，每个 profile 绑定一个**原生 harness** 和一个模型，Agent 可以单独覆盖 profile。

核心原则：

- **模型族与原生 harness 绑定**：DeepSeek 走 DeepSeek Harness，OpenAI 走 Codex CLI，Kimi 走 Kimi Code 官方 CLI。
- **不做协议转换**：不引入 Anthropic 兼容网关，不把某一家模型的请求改写成另一家的协议。
- **不做跨族回退**：某个 profile 失败时只按 failure class 重试或人工阻塞，不会自动切到另一族的 harness；跨族切换必须显式改 profile。

---

## 1. 模型族与 harness 映射

| 模型族 | `harness` | 使用的 CLI | 默认 profile |
|---|---|---|---|
| DeepSeek | `dsh_headless` | DeepSeek Harness（DSH）headless profile | `deepseek` |
| OpenAI | `codex_exec` | Codex CLI（`codex exec`） | `openai` |
| Kimi | `kimi_code` | `@moonshot-ai/kimi-code` 官方 CLI | `kimi` |
| openJiuwen | `openjiuwen` | 未实现，仅保留工厂名称与配置扩展点 | — |

工厂代码位于 `scripts/automm/llm/__init__.py`，`harness` 值决定实例化哪个适配器：

- `dsh_headless` → `scripts/automm/llm/dsh.py` 的 `DshHeadlessProvider`
- `codex_exec` → `scripts/automm/llm/codex.py` 的 `CodexProvider`
- `kimi_code` → `scripts/automm/llm/kimi.py` 的 `KimiCodeProvider`

已知 `harness` 之外的名称会在加载 profile 时直接报 `ProviderConfigError`。

---

## 2. 配置文件与解析顺序

### 2.1 `config/agent_runtime.yaml`

顶层关键字段：

```yaml
enabled: true
default_profile: deepseek
profiles:
  deepseek: { ... }
  openai: { ... }
  kimi: { ... }
output_schema: config/agent_response.schema.json
registry: config/agent_registry.yaml
```

- `default_profile`：Agent 未显式指定 profile 时使用；必须存在且未禁用。
- `profiles`：profile 名到配置的映射；名称唯一。
- `output_schema`：所有 harness 共用的响应 schema。`invoke_agent` 在运行时把它注入 profile，供 Codex 的 `--output-schema` 使用。
- `registry`：Agent 注册表路径。

### 2.2 按 Agent 覆盖：`config/agent_registry.yaml`

在 Agent 条目下增加可选的 `profile`：

```yaml
agents:
  sanity-checker:
    prompt: agents/sanity-checker.md
    stages: [sanity_check, computation_result]
    profile: openai
```

解析优先级：

1. Agent registry 中该 Agent 的 `profile`；
2. 否则使用 `agent_runtime.yaml` 的 `default_profile`。

每次动作都会重新解析 profile，因此修改配置后不需要重启 daemon。以下情况会在 `validate-config` 与运行时失败：

- `profile` 指向不存在的名称；
- `profile` 被 `enabled: false` 禁用；
- Agent 本身未注册或已禁用；
- profile 含未知字段（避免拼写错误静默生效）。

运行时实际使用的 profile、harness、model 会写入 `runtime/actions/<action_id>/status.json` 与 `invoke_agent` 返回的 `meta`，便于追溯。

### 2.3 超时

- profile 的 `timeout_seconds` 优先于阶段超时（`stage_timeout_seconds`）。
- 不设置时沿用阶段超时；`0` 表示不设超时。
- 超时会终止进程树、保存 stdout/stderr，并按既有 `AgentTimeoutError` 路径重试。

---

## 3. 通用字段

所有 harness 共享以下字段：

| 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `harness` | string | 必填 | `dsh_headless` / `codex_exec` / `kimi_code` / `openjiuwen` |
| `enabled` | bool | `true` | `false` 时该 profile 不可被引用；默认 profile 禁用会使校验失败 |
| `executable` | string | 各 harness 不同 | CLI 可执行文件。相对路径按项目根解析，也会查 PATH；Codex 特殊支持 `auto` |
| `executable_args` | list[string] | `[]` | 放在 `executable` 之后、harness 参数之前的固定前缀参数。Kimi 用它指向 `main.mjs` |
| `extra_args` | list[string] | `[]` | 追加到命令末尾的参数。**不得**通过参数传入密钥 |
| `extra_env` | map[string]string | `{}` | 追加到子进程环境。只放非敏感变量；**不得写密钥** |
| `timeout_seconds` | int | 继承阶段超时 | 单次动作超时；`0` 表示不限时 |

环境隔离：适配器通过 `build_env` 构造子进程环境，会移除宿主会话可能泄漏的 provider 变量（`ANTHROPIC_*`、`CLAUDE*`、`OPENAI_*`、`DEEPSEEK_*`、`KIMI_*`、`MOONSHOT_*`、`GEMINI_*`、`GOOGLE_*`、`AZURE_OPENAI_*`），再注入当前 harness 所需的变量。

---

## 4. DeepSeek：`dsh_headless`

### 4.1 字段

| 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `dsh_home` | path | `~/.dsh` | DSH 数据目录；必须存在，且包含 `profiles/<dsh_profile>` |
| `dsh_profile` | string | `headless` | 使用的 DSH profile 名 |
| `provider` | string | 必填 | DSH provider ID，例如 `deepseek-official` |
| `model` | string | 必填 | 模型 ID，例如 `deepseek-v4-pro` |
| `permission_mode` | string | `workspace-write` | 传给 `--permission-mode` |
| `approval_policy` | string | `never` | 传给 `--approval-policy`（`ask` / `never`） |
| `patch_config` | map | `{}` | 合并进 `agent-default-model` patch 的额外字段；不能包含 `provider`、`model` |

`executable` 建议写成 `dsh.cmd` 的绝对路径（例如本机 `D:/deepseek harness/resources/runtime/cli/bin/dsh.cmd`）。

### 4.2 命令与 prompt

```text
<executable> [executable_args...] --profile <dsh_profile> --patch <run_dir>/dsh_patch.yml \
  --permission-mode <permission_mode> --approval-policy <approval_policy> [extra_args...] -
```

- prompt 走 **stdin**；末尾的 `-` 表示从 stdin 读取任务文本。
- 工作目录是项目根，DSH 会自动加载根目录的 `AGENTS.md`。
- 最终 assistant 文本写到 stdout；stderr 是诊断/推理过程。适配器只在 stdout 上提取 JSON。

### 4.3 模型切换：`--patch` 与 `agent-default-model`

每次动作都会在 `runtime/actions/<action_id>/dsh_patch.yml` 生成一个临时 patch：

```yaml
- id: agent-default-model
  config:
    provider: deepseek-official
    model: deepseek-v4-pro
```

要点：

- **`provider` 和 `model` 必须成对提供**：`agent-default-model` 是整体替换，不是逐字段合并。
- `profile.provider` / `profile.model` 始终写入 patch；`patch_config` 只能追加其他键（例如 `reasoningEffort`），若包含 `provider`/`model` 会直接报 `ProviderConfigError`。
- 适配器不会修改 `~/.dsh/profiles/headless` 下的任何持久配置；切换模型只需要改 `config/agent_runtime.yaml` 的 profile。
- 更换 DeepSeek 模型时，把 `model` 改成目标模型 ID（必要时同步 `provider`），然后重跑 smoke。

### 4.4 常见失败

- `找不到 dsh CLI`：`executable` 路径错误或文件不存在。
- `dsh_home 不存在` / `dsh profile 不存在`：先在 DSH 中初始化 headless profile，或修正 `dsh_home`。
- 认证错误（stderr 含 401/403/unauthorized 等）会抛 `ProviderAuthError`，按 `external_human_required` 进入人工阻塞；凭据由 DSH 自己管理（见第 9 节）。

### 4.5 headless 凭据存储（0.2.2 的重要差异）

DSH 0.2.2 的 headless profile **默认禁用托管凭据存储**（`credentials`/`authorization`/`deepseek-account` 均为 `disabled: true`），按设计只使用“启动环境 → `<cwd>/.env` → `$DSH_HOME/.env`”的凭据链。AutoMM 出于安全会从子进程环境中移除宿主会话的 `DEEPSEEK_*`、`OPENAI_*` 等变量，因此不能依赖“在启动 AutoMM 的终端里 export DEEPSEEK_API_KEY”。

推荐做法（DSH headless README 官方方案）：在 `~/.dsh/profiles/headless/cordis.patch.yml` 末尾恢复托管凭据存储：

```yaml
- id: credentials
  disabled: false
- id: authorization
  disabled: false
- id: deepseek-account
  disabled: false
```

这样 headless 会读取 `$DSH_HOME/.credentials.yaml` 中已有的 `refs.DEEPSEEK_API_KEY`，AutoMM 不需要接触密钥。也可以改用在 `$DSH_HOME/.env` 中设置 `DEEPSEEK_API_KEY`（该文件在 DSH home 内，**不要**放到仓库目录）。修改后重新运行：

```bash
.venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile deepseek
```

若仍报 `MISSING_CREDENTIAL`，用 `dsh --profile headless --dump-config` 确认 `credentials` 条目没有 `disabled: true`，并检查凭据文件路径是否为当前 `DSH_HOME` 下的 `.credentials.yaml`。

---

## 5. OpenAI：`codex_exec`

### 5.1 字段

| 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `codex_home` | path | `~/.codex` | `CODEX_HOME`；Codex 的登录态与配置都留在这里 |
| `model` | string | 必填 | 传给 `--model`，例如 `gpt-6-luna` |
| `sandbox` | string | `workspace-write` | 非 bypass 模式下的 `--sandbox`：`read-only` / `workspace-write` / `danger-full-access` |
| `bypass_approvals` | bool | `true` | `true` 时追加 `--dangerously-bypass-approvals-and-sandbox` |
| `skip_git_repo_check` | bool | `true` | `true` 时追加 `--skip-git-repo-check` |
| `config_profile` | string | 空 | 非空时追加 `-p <name>`，加载 `$CODEX_HOME/<name>.config.toml` |

### 5.2 可执行文件发现

`executable: auto`（默认）按以下顺序查找：

1. PATH 上的 `codex`；
2. `C:\Program Files\WindowsApps\OpenAI.Codex_*\app\resources\codex.exe`（按版本目录排序取最新）；
3. Windows 11 无法枚举 `WindowsApps` 时，回退到当前用户 AppX 注册表定位包根。

显式指定 `executable` 时只查 PATH 和项目内文件，不再自动发现。`probe()` 会运行 `codex --version` 与 `codex exec --help`，确认 `--output-schema`、`--output-last-message`、`--skip-git-repo-check`、`--json`、`--sandbox`、`--approve-for-me`、`--cd`、`--dangerously-bypass-approvals-and-sandbox`、`--profile` 等能力存在。

### 5.3 命令与结构化输出

```text
<codex> exec - -C <项目根> \
  --output-schema <config/agent_response.schema.json 的绝对路径> \
  --output-last-message <run_dir>/response.json \
  --json --color never \
  [--skip-git-repo-check] \
  --model <model> [-p <config_profile>] \
  [--dangerously-bypass-approvals-and-sandbox | --sandbox <sandbox> --approve-for-me] \
  [extra_args...]
```

- prompt 走 **stdin**；`exec -` 表示从 stdin 读取。
- `--output-schema` 把响应的 JSON Schema 交给 Codex，要求其输出符合 `config/agent_response.schema.json`。
- `--output-last-message` 把最终一条消息写入 `runtime/actions/<action_id>/response.json`；适配器直接读取该文件，文件缺失视为传输失败。
- `--json` 事件流写入 stdout，仅作为原始日志保留，不参与响应解析。
- `-p <config_profile>` 是 Codex 的配置 profile（`$CODEX_HOME/<name>.config.toml`），不要与 Kimi 的 `-p/--prompt` 混淆。

### 5.4 bypass 与 sandbox 的互斥语义

- `bypass_approvals: true`：命令带 `--dangerously-bypass-approvals-and-sandbox`，**不会**再传 `--sandbox`；此时 `sandbox` 字段被忽略。
- `bypass_approvals: false`：命令带 `--sandbox <sandbox> --approve-for-me`，且 `sandbox` 必须是合法值。
- 当前默认 profile 使用完全 bypass，适合无人值守、只在项目目录内运行的场景。**这会让 Codex 在无审批情况下执行命令与写文件，风险自负**；如不需要，改成 `bypass_approvals: false` 并选择更严格的 sandbox。
- Codex 的 ChatGPT 登录态或 API key 由 Codex 自身维护在 `CODEX_HOME`（如 `auth.json` / `config.toml`）。AutoMM 不读取、不复制这些凭据，也不会把它们写入日志。

---

## 6. Kimi：`kimi_code`

### 6.1 字段

| 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `kimi_code_home` | path | `runtime/kimi-code-home` | 项目内的 `KIMI_CODE_HOME`；适配器负责创建 |
| `api_key_file` | path | 空 | 含 `apiKey` 字段的 JSON 文件（例如 Kimi 桌面端 Daimon 分享的 key 文件） |
| `api_key_env` | string | `KIMI_API_KEY` | 优先读取的环境变量名 |
| `config_file` | path | 空 | 源 `config.toml`；仅在目标文件不存在时用于 seed |
| `base_url` | string | 空 | 非空时注入 `KIMI_CODE_BASE_URL` |
| `model` | string | 必填 | Kimi CLI 的模型**别名**，必须存在于 seed 后的 `config.toml`；当前 profile 使用 `k3-agent` |
| `max_prompt_chars` | int | `30000` | prompt 长度上限；超过时报配置错误，不做静默截断 |
| `executable` | string | `node` | 运行 `main.mjs` 的 Node 可执行文件 |
| `executable_args` | list[string] | 必填 | 第一项必须是 `main.mjs` 路径 |

### 6.2 命令与 prompt

```text
node <main.mjs> -m <model> -p <prompt> --output-format text [extra_args...]
```

- Kimi 官方 CLI 的非交互入口是 `-p/--prompt <prompt>`，因此 prompt 作为**命令行参数**传入，不走 stdin。
- `--output-format text` 输出最终 assistant 文本；适配器从 stdout 解析 JSON。
- 退出码语义：`0` 成功；`75` 视为可重试失败（按 `agent_transport` 重试）；其他非零退出码按 stderr 分类，明确认证失败时抛 `ProviderAuthError`。
- `max_prompt_chars` 防止 Windows 命令行过长与超限 prompt；AutoMM 的 Agent prompt 一般在 10000 字符量级。
- 若报 `provider.auth_error: You've reached your usage limit ... resource_exhausted: rate limit exceeded`，那是 Kimi 账户配额/速率限制，不是 profile 或 key 错误：等待配额刷新或升级账户后重跑。适配器按配额/限流标记将其归类为可重试的 `ProviderError`（`agent_transport`），不会作为凭据失败进入人工阻塞。

### 6.3 `config.toml` 要求与 seed

Kimi Code CLI 依赖 `$KIMI_CODE_HOME/config.toml` 中的 provider、model 别名和权限规则。适配器行为（`scripts/automm/llm/kimi.py`）：

1. 目标路径为 `<kimi_code_home>/config.toml`（默认 `runtime/kimi-code-home/config.toml`）。
2. **目标已存在**：直接使用，**绝不覆盖**。想重新 seed，先手动删除该文件。
3. **目标不存在且 profile 提供 `config_file`**：把源文件原子复制到目标（先写同目录临时文件，再 `os.replace`）。
4. 目标不存在且没有 `config_file`：报 `ProviderConfigError`，提示先完成 Kimi Code 登录/初始化或提供 `config_file`。

`model` 必须是该 `config.toml` 中 `[models.<alias>]` 定义的别名。模板早期填写的是 `kimi-code`，但该名称只在部分 OAuth 供应的配置中存在；**Kimi 桌面端 Daimon 分享配置通常没有这个别名**，CLI 会报 `Model "kimi-code" is not configured in config.toml.`。验收时已按实际 config 的 `default_model` 改为 `k3-agent`（同文件还提供 `k2p6-agent`、`k2d8-preview`、`k3d1-agent` 等别名）。换用其他来源的 config 时，用 `node <main.mjs> --help` 或查看 `[models.*]` 小节确认可用别名，再修改 `config/agent_runtime.yaml` 的 `model`；不需要改源 config。

> seed 后的 `runtime/kimi-code-home/config.toml` 可能包含凭据。`runtime/` 已被 `.gitignore` 忽略；不要把它提交、复制进 `config/` 或粘贴到日志中。

### 6.4 API key 与 base URL

API key 读取顺序：

1. profile 的 `api_key_env`（默认 `KIMI_API_KEY`）对应的环境变量；
2. profile 的 `api_key_file` 中 JSON 的 `apiKey` 字段。

适配器把 key 注入子进程环境变量 `KIMI_API_KEY`，并设置 `KIMI_CODE_HOME`；`base_url` 非空时同时设置 `KIMI_CODE_BASE_URL`。key 不会出现在命令、日志、`status.json` 或 `meta` 中。

### 6.5 Windows：`KIMI_SHELL_PATH`

Kimi Code CLI 在 Windows 上依赖 Git Bash。若 CLI 找不到 Bash，可在该 profile 的 `extra_env` 指定绝对路径：

```yaml
extra_env:
  KIMI_SHELL_PATH: "C:/Program Files/Git/bin/bash.exe"
```

`KIMI_SHELL_PATH` 不是密钥，放在 profile 里是安全的。只有 CLI 探测失败时才需要设置。

### 6.6 项目内安装

CLI 固定在项目内安装，避免全局 `.cmd` 对含引号/换行 prompt 的二次解析：

```text
tools/kimi-cli/package.json          # 依赖 @moonshot-ai/kimi-code@2.6.3
tools/kimi-cli/node_modules/@moonshot-ai/kimi-code/dist/main.mjs
```

`node_modules/` 已被 `.gitignore` 忽略。安装步骤见 `SETUP.md` 2.3。

---

## 7. 真实往返 smoke

三个 profile 各有一个最小 prompt smoke（会消耗少量模型额度）：

```bash
.venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile deepseek
.venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile openai
.venv/Scripts/python.exe scripts/smoke_llm_roundtrip.py --profile kimi
```

脚本会：

1. 加载 profile 并调用 `probe()`（只探测 CLI 与必需参数，不调用模型）；
2. 用该 harness 的真实调用路径发送最小 prompt；
3. 校验响应符合 `config/agent_response.schema.json`；
4. 打印 profile、harness、model、returncode、耗时、response 和 stderr 尾部（不含密钥）。

退出码 `0` 且 response 通过 schema 校验才算成功。失败时脚本打印结构化错误 JSON，包含 `returncode`、`error` 与 `stderr_tail`，不会伪造成功。

> Windows 控制台若为 GBK 编码，CLI 错误信息中的 `•` 等字符可能让错误 JSON 打印失败（`UnicodeEncodeError`）。先设置 `PYTHONIOENCODING=utf-8`（PowerShell：`$env:PYTHONIOENCODING = "utf-8"`）再重跑，即可看到真实错误。

---

## 8. 失败分类与恢复

| 异常 | failure class | 行为 |
|---|---|---|
| `ProviderConfigError`（profile/可执行文件/密钥缺失、openJiuwen 未实现） | `external_human_required` | 人工阻塞，修正配置后继续 |
| `ProviderAuthError`（CLI 明确报告 401/403/认证失败） | `external_human_required` | 人工重新登录或更新凭据 |
| `ProviderError`（进程失败、无法解析 JSON、可重试退出码） | `agent_transport` | 由 Runner 按 `timeout_policy` 重试 |
| 响应 schema / 上下文不匹配 | `harness_invariant` | 严格失败并上报 |
| 超时 | 既有 `AgentTimeoutError` 路径 | 保存日志后重试 |

Kimi 的 `usage limit`、`quota`、`rate limit`、`resource_exhausted` 等配额/限流标记优先按可重试传输错误处理，不会误判为认证失败。

不会因为一个模型族失败就切换到另一个模型族；跨族切换只能通过改 profile。

---

## 9. 安全

- **密钥只在运行时读取**：DSH 凭据留在 `DSH_HOME/.credentials.yaml`；Codex 登录态留在 `CODEX_HOME`；Kimi key 来自 `api_key_env` 或 `api_key_file`。AutoMM 只检查存在性，不打印值。
- **不进入日志/元数据**：`stdout.log`、`stderr.log`、`status.json`、`agent_events.jsonl` 和 `meta` 均不含密钥。适配器只注入自己的环境变量。
- **`extra_env` 不得写密钥**：配置文件会进入版本库；只放 `KIMI_SHELL_PATH` 这类非敏感变量。
- **完全 bypass 的风险**：Codex 默认 `bypass_approvals: true`，等价于 `--dangerously-bypass-approvals-and-sandbox`。只在可信项目、无人值守、限定工作目录的场景使用。DSH 的 `permission_mode`/`approval_policy` 同理，按最小权限配置。
- **seed 的 Kimi config 含凭据**：`runtime/kimi-code-home/` 已在 `.gitignore` 中；不要提交、不要复制到 `config/`、不要贴到 issue 或日志。
- 提交前建议运行 `git grep -nE "sk-[A-Za-z0-9]{16,}"` 自检（应无输出）。

---

## 10. openJiuwen 扩展点（未实现）

本阶段只在工厂和校验层保留名称，不安装、不导入 openJiuwen 包：

- profile 若写 `harness: openjiuwen`，`validate-config` 直接 FAIL，运行时 `load_profile`/`get_provider` 抛 `ProviderConfigError("openjiuwen harness 本阶段仅保留扩展点，尚未实现")`。
- 可保留如下注释示例，但不要启用：

```yaml
# profiles:
#   openjiuwen:
#     harness: openjiuwen
#     # 本阶段未实现，启用会导致 validate-config 失败
```

后续新增适配器的最小步骤：

1. 新建 `scripts/automm/llm/openjiuwen.py`，实现 `LLMProvider` 的 `probe()`、`prepare()`、`extract_response()`，并设置 `backend = "openjiuwen"`；`prepare()` 返回 `Invocation`（命令、stdin、环境、输出路径、meta），`extract_response()` 返回解析后的 dict 或抛 `ProviderError`/`ProviderAuthError`。
2. 在 `scripts/automm/llm/__init__.py` 的 `_PROVIDERS` 注册 `"openjiuwen": OpenJiuwenProvider`，并移除工厂里的未实现分支。
3. 在 `scripts/automm/llm/profiles.py` 的 `_HARNESS_FIELDS` 增加该 harness 的专属字段白名单，并在 `validate_profiles` 中增加对应校验（参考 `_validate_kimi`）。
4. 增加单元测试（命令构造、输出解析、认证分类）和最小 smoke；同步更新本文档。
5. `agent_runtime.py`、`failure_policy.py` 不需要改动：只要适配器遵守 `LLMProvider` 契约，profile 解析、超时、schema 校验、事务与失败分类会自动生效。

---

## 11. 已验证版本

| 组件 | 版本 |
|---|---|
| DeepSeek Harness（DSH） | 0.2.2-rc.3 |
| Codex CLI | 0.171.0-alpha.13（AppX 包 26.1117.3838.0） |
| Kimi Code CLI（`@moonshot-ai/kimi-code`） | 2.6.3 |
| Node.js | 24.22.1（Kimi CLI 要求 >= 22.19） |

原生 CLI 契约可能随版本变化：各适配器的 `probe()` 会检查必需参数，避免在缺少能力时静默运行。升级 CLI 后请重跑对应 smoke。
