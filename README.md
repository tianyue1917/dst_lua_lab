# DST Lua Lab

[![CI](https://github.com/tianyue1917/dst_lua_lab/actions/workflows/ci.yml/badge.svg)](https://github.com/tianyue1917/dst_lua_lab/actions/workflows/ci.yml)

DST Lua Lab 是一个面向《饥荒联机版》MOD 的可审计、可重复、离线 Lua 调试环境。它在独立 Python Worker 和全新 Lua VM 中加载 MOD，记录模块解析、注册行为、RPC、持久化和缺失 Native API，并保持目标 MOD 只读。

它不是完整的 DST 引擎模拟器。渲染、网络、userdata 和服务端真实落盘不会被伪造；遇到尚未实现的原生边界时，Lab 会生成明确诊断并停止。

## 主要能力

- `lua51`、`luajit20`、`luajit21` Runtime Adapter。
- Worker 级墙钟超时，可终止 Lua 死循环。
- Directory、ZIP、Overlay VFS，包含路径逃逸保护和来源 Hash。
- `algorithm` Profile：固定 userid、时间和随机种子，捕获动态 `load` / `loadstring` Chunk。
- `modload` Profile：隔离 MOD env、`require` 缓存、`modimport`、`modinfo.lua` 默认配置和常用 DST 注册面。
- Prefab、Asset、Recipe、Action、Stategraph、Hook 和 RPC 声明捕获。
- 隔离内存 Persistence、虚拟 Scheduler 和严格 Missing Native 诊断。
- 可插拔 Capability Module 与 Case Pack。
- JSONL Trace、输入证据、结果、扩展状态和 Markdown 摘要。

当前可执行 Profile：

| Profile | 用途 | 是否需要 `scripts.zip` |
| --- | --- | --- |
| `algorithm` | 独立 Lua 算法、编码和多 Runtime 对比 | 否 |
| `modload` | 加载 `modinfo.lua`、`modmain.lua` 并捕获 DST 边界 | 是 |
| `frontend` | 使用客户端角色、`ThePlayer`、`TheInput`、`TheFrontEnd` Fixture | 是 |
| `server-sim` | 使用专用服务器角色、世界、RPC、内存 Persistence Fixture | 是 |

Frontend 与 Server-Sim 仍是确定性 Fixture，不是渲染器或真实服务器进程。

## 环境要求

- Python 3.11 或更高版本。
- Windows PowerShell 或常规 Linux shell。
- 调试 MOD 时，需要从你自己的 DST 安装中取得 `scripts.zip`。该文件包含 Klei 游戏资源，不属于本仓库，也不应重新分发。

Steam 安装中常见位置：

```text
<SteamLibrary>/steamapps/common/Don't Starve Together/data/databundles/scripts.zip
```

## 安装

```powershell
git clone https://github.com/tianyue1917/dst_lua_lab.git
cd dst_lua_lab
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python dstlab.py --help
```

Linux 激活虚拟环境时使用：

```bash
source .venv/bin/activate
```

根目录的 `dstlab.py` 会自动加入 `src/`，因此不要求把项目安装成命令；但运行时依赖仍必须存在。只想直接运行入口时至少安装：

```powershell
python -m pip install "lupa>=2.8"
python dstlab.py --help
```

从 Wheel 安装后使用 console entry：

```powershell
dstlab --help
dstlab doctor --mod "C:\path\to\target-mod"
```

下文的 `python dstlab.py` 在 Wheel 安装态都可替换为 `dstlab`。内置 Module/Case 会随包提供；报告、配置和脚手架默认写入 `%LOCALAPPDATA%\dst-lua-lab`（Windows）或 `$XDG_DATA_HOME/dst-lua-lab`（Linux）。可用 `DSTLAB_HOME` 显式选择另一个**受信任**的 Lab Home。Checkout 始终使用仓库根目录，不读取目标 MOD 当前目录下的 Python 扩展。

## scripts.zip 放在哪里

推荐不复制游戏文件，直接把原路径传给 `--scripts-zip`：

```powershell
python dstlab.py debug-mod `
  --mod "C:\path\to\target-mod" `
  --scripts-zip "C:\path\to\Don't Starve Together\data\databundles\scripts.zip"
```

推荐保存一次本机路径。配置写入被 Git 忽略的 `.dstlab/config.toml`：

```powershell
python dstlab.py config set-scripts-zip "C:\path\to\scripts.zip"
python dstlab.py config show
python dstlab.py config clear-scripts-zip
```

解析顺序为：命令行 `--scripts-zip`、环境变量 `DSTLAB_SCRIPTS_ZIP`、本机配置、Lab Home 上一级的默认文件。Checkout 常用以下默认布局：

```text
workspace/
├── scripts.zip
└── dst_lua_lab/
    └── dstlab.py
```

Wheel 安装建议始终使用 `config set-scripts-zip`，避免依赖用户数据目录的自动默认位置。

也可以把文件放在仓库根目录，但此时必须显式传入：

```powershell
python dstlab.py debug-mod --mod "C:\path\to\target-mod" --scripts-zip ".\scripts.zip"
```

仓库根目录的 `/scripts.zip` 已被 `.gitignore` 排除。提交前仍应使用 `git status` 检查暂存区。

## 第一次调试 MOD

1. 一次检查 Python、三个 Lua Runtime、`scripts.zip`、扩展计划和目标入口：

```powershell
python dstlab.py doctor --mod "C:\path\to\target-mod"
```

Doctor 会输出每项状态，并在输入有效时给出可复制的 `suggested=` 调试命令。机器可读输出使用 `--json`。

2. 单独检查目标目录及入口 Hash：

```powershell
python dstlab.py inspect-mod --mod "C:\path\to\target-mod"
```

3. 使用通用 Case Pack 启动只读调试：

```powershell
python dstlab.py debug-mod `
  --mod "C:\path\to\target-mod" `
  --scripts-zip "C:\path\to\scripts.zip" `
  --runtime luajit20 `
  --timeout 15
```

4. 查看命令输出的 `report=<绝对路径>`。优先阅读：

- `summary.md`：本次运行摘要。
- `result.json`：状态、运行结果和最早错误。
- `unsupported.json`：尚未覆盖的 Native API。
- `registrations.json`：Prefab、Asset、Recipe、Action、Stategraph 和 Hook 捕获。
- `extensions.json`：实际加载的 Module/Case 及 after-run 输出。
- `trace.jsonl`：按时间顺序记录的详细证据。

`debug-mod` 会启用 `general_mod_debug` Case Pack，并加载 DST 基础形状、strict env、RPC、持久化和虚拟调度器能力。命令还会输出一行 `diagnostic=...` JSON，便于快速定位最早缺口。

客户端或专用服务器分支使用：

```powershell
python dstlab.py debug-mod --profile frontend --mod "C:\path\to\mod"
python dstlab.py debug-mod --profile server-sim --mod "C:\path\to\mod"
```

这两条命令分别自动选择 `frontend_mod_debug`、`server_sim_debug` Case。

## 常用命令

运行不依赖游戏资源的算法实验：

```powershell
python dstlab.py run --profile algorithm --runtime luajit20 --source "return 6 * 7"
```

比较多个 Lua Runtime：

```powershell
python dstlab.py diff-runtime `
  --runtime lua51,luajit20,luajit21 `
  --source "return string.char(65,0,255,66)"
```

直接使用 `modload` Profile：

```powershell
python dstlab.py run `
  --profile modload `
  --mod "C:\path\to\target-mod" `
  --scripts-zip "C:\path\to\scripts.zip"
```

需要其他 MOD 提供模块时，可重复传入依赖目录：

```powershell
python dstlab.py debug-mod `
  --mod "C:\path\to\target-mod" `
  --scripts-zip "C:\path\to\scripts.zip" `
  --dependency "C:\path\to\first-dependency" `
  --dependency "C:\path\to\second-dependency"
```

从已有报告汇总尚未覆盖的 Native API：

```powershell
python dstlab.py list-missing-api --report "C:\path\to\report"
```

## 可插拔扩展

长期复用的调试能力放在 `modules/<module-id>/`，单个目标的适配放在 `casepacks/<case-id>/`。只有 Worker 会导入本次计划选中的入口。

仓库内含两个纯合成示例：

- `modules/example_trace`：Capability Module 清单与入口示例。
- `casepacks/example_case`：声明依赖 Module 的 Case Pack 示例。

创建安全模板：

```powershell
python dstlab.py module init component_trace
python dstlab.py case init example_target
python -m pytest modules/component_trace/tests casepacks/example_target/tests -q
```

脚手架拒绝覆盖已有目录、路径逃逸、平台账号式 ID 和纯数字 Workshop 式 ID。

```powershell
python dstlab.py module list
python dstlab.py module doctor
python dstlab.py module enable example_trace
python dstlab.py module disable example_trace

python dstlab.py case list
python dstlab.py case validate example_case
python dstlab.py case test example_case
python dstlab.py run --case example_case --source "return 42"
```

外部 Case Pack 可以安全挂载和卸载：

```powershell
python dstlab.py case mount "C:\path\to\casepack"
python dstlab.py case validate external_case --mod "C:\path\to\target-mod"
python dstlab.py case unmount external_case --purge-generated
```

Manifest、`register(context)`、Lua Bootstrap、Native Handler 和 Case Pack 的完整开发方法见 [公共开发指南](docs/development-guide.md)。

## 受控回放

Hook、Prefab、RPC 和 Stategraph 回调默认只捕获，不执行。需要验证构造逻辑时，创建显式 JSON 计划：

```json
[
  {"kind": "prefab_postinit", "target": "example_item", "strict": true},
  {"kind": "prefab_constructor", "target": "example_item"},
  {
    "kind": "mod_rpc",
    "rpc_type": "server",
    "namespace": "example_namespace",
    "name": "ping",
    "args": ["fixture_payload"]
  }
]
```

```powershell
python dstlab.py debug-mod `
  --mod "C:\path\to\target-mod" `
  --replay-plan "C:\path\to\replay-plan.json"
```

传入计划时 CLI 自动选择 `controlled_replay` Module。当前支持：

- `prefab_postinit`
- `component_postinit`
- `prefab_constructor`
- `mod_rpc`
- `stategraph_state`

回放只使用合成实体和虚拟角色。成功表示回调在 Fixture 上运行完毕，不证明真实游戏效果。完整 Schema 见 [`modules/controlled_replay/README.md`](modules/controlled_replay/README.md)。

## 测试

默认测试会临时生成一个最小、纯合成的 `scripts.zip`，不需要也不包含 Klei 游戏脚本：

```powershell
python -m pip install pytest
python -m pytest -q
python tools/scan_sensitive.py
```

可选地，用环境变量验证你本机的游戏脚本和一个只读 MOD：

```powershell
$env:DSTLAB_SCRIPTS_ZIP = "C:\path\to\scripts.zip"
$env:DSTLAB_SMOKE_MOD = "C:\path\to\target-mod"
python -m pytest -q
```

未设置这两个变量时，对应的本机集成测试会显示为 `skipped`，不代表 Core 测试失败。

CI 在 Windows 与 Ubuntu 上运行 Core、Wheel 安装烟雾测试和敏感内容扫描。Wheel 测试会证明安装后仍可发现并执行内置 Module/Case。

## 退出码与排障

| 退出码 | 含义 | 常见处理 |
| --- | --- | --- |
| `0` | 运行成功 | 阅读报告并继续增加目标断言 |
| `1` | Lua 编译或运行错误 | 查看 `result.json` 和 `errors.txt` |
| `2` | 参数、路径、Manifest 或 Profile 配置错误 | 检查命令参数与输入文件 |
| `3` | 遇到未覆盖的 Native API | 查看 `unsupported.json`，添加经过验证的 Module/Case 适配 |
| `4` | Worker 超时 | 检查死循环，必要时调整 `--timeout` |
| `5` | `diff-runtime` 结果不一致 | 检查各 Runtime 的结果差异 |
| `6` | Lab 内部错误 | 查看 `errors.txt` 并保留最小复现 |

退出码 `3` 是严格边界诊断，不等于游戏 MOD 或 Lab 进程崩溃。不要用无条件空函数掩盖缺失 Native；先证明真实调用契约，再把最小实现放入通用 Module 或目标 Case Pack。

## 输出与清理

每次运行会在以下位置生成可删除的派生文件：

- `reports/<case-id>/<run-id>/summary.md`
- `work/<case-id>/<run-id>/request.json`
- `environment.json`、`inputs.json`、`result.json`
- `trace.jsonl`
- `extensions.json`、`registrations.json`
- `chunks/*.bin` 和 Worker stdout/stderr

未选择 Case 时使用 `_core` 命名空间。`work/` 和 `reports/` 已被 Git 忽略，仅保留目录占位文件。

清理单个 Case 的派生文件：

```powershell
python dstlab.py case clean example_case
```

`case clean` 和 `case unmount --purge-generated` 只允许删除 Lab 内对应 Case 的 `work/`、`reports/` 命名空间，不会删除外部 Case、原始 MOD、Workshop 内容或存档。

## 真实性与数据边界

- MOD 入口和从用户提供的 VFS 解析到的 Lua 标记为真实输入。
- userid、固定时间、随机种子和测试脚本标记为 Fixture。
- 动态 Chunk 只证明已捕获或执行，不代表真实 DST 原生效果。
- Prefab/Hook 回调默认只捕获声明，不执行真实引擎效果。
- 只有非空 `--replay-plan` 才允许 `controlled_replay` 执行精确匹配的回调。
- 未注册 Native API 会明确失败，不会由万能空函数伪造成功。
- Lab 不修改原始 MOD、游戏脚本或存档。
- Python 扩展入口属于受信任的本地代码；只加载你审查过的 Module 和 Case Pack。
- 报告可能包含输入路径和 MOD 运行痕迹；提交代码前应清空 `work/`、`reports/`，并检查暂存区。

本仓库不包含游戏脚本、Workshop MOD、存档、日志、账号标识、兑换码或针对特定 MOD 的逆向产物。

版本变化见 [CHANGELOG](CHANGELOG.md)。本项目采用 [MIT License](LICENSE)。
