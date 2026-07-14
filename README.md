# DST Lua Lab

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

## 环境要求

- Python 3.11 或更高版本。
- 调试 MOD 时，需要从你自己的 DST 安装中取得 `scripts.zip`，通常位于游戏的 `data/databundles/` 目录。该文件包含 Klei 游戏资源，不属于本仓库，也不应重新分发。

## 安装

```powershell
cd "C:\path\to\dst-lua-lab"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

也可以不安装，直接在仓库根目录运行 `python dstlab.py`。

## 快速开始

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

检查 MOD 目录：

```powershell
python dstlab.py inspect-mod --mod "C:\path\to\target-mod"
```

使用通用 Case Pack 一键调试 MOD：

```powershell
python dstlab.py debug-mod `
  --mod "C:\path\to\target-mod" `
  --scripts-zip "C:\path\to\data\databundles\scripts.zip" `
  --runtime luajit20 `
  --timeout 15
```

需要其他 MOD 提供模块时，可重复传入依赖目录：

```powershell
python dstlab.py debug-mod `
  --mod "C:\path\to\target-mod" `
  --scripts-zip "C:\path\to\scripts.zip" `
  --dependency "C:\path\to\dependency-mod"
```

`debug-mod` 会启用 `general_mod_debug` Case Pack，并加载 DST 基础形状、strict env、RPC、持久化和虚拟调度器能力。命令结束时会输出 `report=<绝对路径>` 和一行 JSON `diagnostic=...`。

## 可插拔扩展

长期复用的调试能力放在 `modules/<module-id>/`，单个目标的适配放在 `casepacks/<case-id>/`。只有 Worker 会导入本次计划选中的入口。

仓库内含两个纯合成示例：

- `modules/example_trace`：Capability Module 清单与入口示例。
- `casepacks/example_case`：声明依赖 Module 的 Case Pack 示例。

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
python dstlab.py case unmount external_case --purge-generated
```

清理命令只允许删除 Lab 内对应 Case 的 `work/` 和 `reports/` 命名空间，不会删除外部 Case、原始 MOD、Workshop 内容或存档。

## 测试

默认测试会临时生成一个最小、纯合成的 `scripts.zip`，不需要也不包含 Klei 游戏脚本：

```powershell
python -m pip install pytest
python -m pytest -q
```

可选地，用环境变量验证你本机的游戏脚本和一个只读 MOD：

```powershell
$env:DSTLAB_SCRIPTS_ZIP = "C:\path\to\scripts.zip"
$env:DSTLAB_SMOKE_MOD = "C:\path\to\target-mod"
python -m pytest -q
```

## 输出

每次运行会在以下位置生成可删除的派生文件：

- `reports/<case-id>/<run-id>/summary.md`
- `work/<case-id>/<run-id>/request.json`
- `environment.json`、`inputs.json`、`result.json`
- `trace.jsonl`
- `extensions.json`、`registrations.json`
- `chunks/*.bin` 和 Worker stdout/stderr

未选择 Case 时使用 `_core` 命名空间。`work/` 和 `reports/` 已被 Git 忽略，仅保留目录占位文件。

## 真实性与数据边界

- MOD 入口和从用户提供的 VFS 解析到的 Lua 标记为真实输入。
- userid、固定时间、随机种子和测试脚本标记为 Fixture。
- 动态 Chunk 只证明已捕获或执行，不代表真实 DST 原生效果。
- 未注册 Native API 会明确失败，不会由万能空函数伪造成功。
- Lab 不修改原始 MOD、游戏脚本或存档。
- 报告可能包含输入路径和 MOD 运行痕迹；提交代码前应清空 `work/`、`reports/`，并检查暂存区。

本仓库不包含游戏脚本、Workshop MOD、存档、日志、账号标识、兑换码或针对特定 MOD 的逆向产物。
