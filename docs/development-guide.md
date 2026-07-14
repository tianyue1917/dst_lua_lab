# DST Lua Lab 公共开发指南

本文面向需要扩展 DST Lua Lab 的开发者，说明当前 Extension API v1 的真实契约。示例全部使用合成名称，不依赖 Workshop MOD、账号、存档或游戏私有数据。

## 1. 先选择扩展类型

### Capability Module

Module 表示可以长期复用的调试能力，例如：

- 捕获一类 RPC 注册和发送。
- 为已验证的 Native API 提供确定性 Fixture。
- 注入严格、可审计的 Lua Bootstrap。
- 在运行后汇总某类事件。

Module 放在 `modules/<module-id>/`。它不应包含某个目标 MOD 的账号、兑换码、完整源码、固定路径或持久化数据。

### Case Pack

Case Pack 表示某个目标或某类 MOD 的适配层，例如：

- 声明需要哪些通用 Module。
- 检查目标目录必须存在的文件或已知 Hash。
- 添加只对该目标成立的最小断言或适配。
- 保存该目标的合成回归测试。

仓库内 Case 放在 `casepacks/<case-id>/`。外部 Case 可以通过 `case mount` 挂载，不需要复制进 Core 仓库。

经验规则：可被多个 MOD 复用且契约已经验证的能力放 Module；仍然依赖单个目标结构的内容放 Case Pack。

## 2. 执行流程

```text
CLI
 ├─ Registry: 发现并校验 Manifest
 ├─ Planner: 解析依赖、冲突和启用状态
 └─ Worker: 校验计划 Hash 后导入 entry
      ├─ register(context)
      ├─ 创建新的 Lua VM
      ├─ 执行 Bootstrap 和目标 Lua
      └─ 写入 reports/ 与 work/
```

管理命令发现 Manifest 时不会导入 Python entry。只有 Worker 执行一次具体运行时，才会导入计划中选中的 `plugin.py` 或 `adapter.py`。

Worker 在导入前重新校验 Manifest Hash、entry 路径和依赖顺序。如果计划生成后文件发生变化，本次运行会失败，而不是执行漂移后的代码。

## 3. 创建 Capability Module

最小目录：

```text
modules/
└── example_capability/
    ├── module.toml
    ├── plugin.py
    ├── README.md
    └── tests/
        └── test_example_capability.py
```

目录名必须与 Manifest 的 `id` 完全一致。

### module.toml

```toml
schema = 1
id = "example_capability"
name = "Example capability"
version = "1.0.0"
api_version = "1"
priority = 100
dependencies = []
conflicts = []
profiles = ["algorithm", "modload"]
entry = "plugin.py"
```

字段说明：

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `schema` | 是 | 当前只能为整数 `1` |
| `id` | 是 | 小写字母或数字开头，最长 64 字符，可含 `._-` |
| `name` | 是 | 人类可读名称 |
| `version` | 是 | 扩展自身版本字符串 |
| `api_version` | 是 | 当前只能为字符串 `"1"` |
| `priority` | 否 | `0..10000`，默认 `100` |
| `dependencies` | 否 | 依赖的 Module ID，Planner 会进行拓扑排序 |
| `conflicts` | 否 | 不能同时启用的 Module ID |
| `profiles` | 否 | 声明预期 Profile；当前公开 Profile 为 `algorithm`、`modload` |
| `entry` | 否 | 相对扩展根目录的 Python 入口，必须使用 `/` 分隔且不能包含 `..` |

`dependencies` 与 `conflicts` 不能重叠，也不能引用自身。

### plugin.py

入口必须定义可调用的 `register(context)`：

```python
from typing import Any


def register(context: Any) -> None:
    context.register_global("DSTLAB_EXAMPLE_ENABLED", True)

    def summarize(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "extension": context.extension_id,
            "profile": context.profile,
            "status": result.get("status"),
        }

    context.register_after_run(summarize)
```

`register(context)` 应只声明本次运行所需能力。不要在模块导入阶段扫描用户目录、访问网络或修改目标 MOD。

## 4. ExtensionContext API v1

| API | 用途 |
| --- | --- |
| `context.extension_id` | 当前扩展 ID |
| `context.kind` | `module` 或 `case` |
| `context.root` | 当前扩展根目录的绝对 `Path` |
| `context.api_version` | 当前 Extension API 版本 |
| `context.profile` | 本次运行的 Profile |
| `context.config` | 只读公共运行配置视图 |
| `read_bytes(path)` | 读取扩展根目录内文件，拒绝绝对路径和目录逃逸 |
| `register_lua_bootstrap(phase, path)` | 注册扩展目录内的 Lua Bootstrap |
| `register_global(name, value)` | 向 Lua 注册 JSON-safe 全局值 |
| `deny_mod_global(name)` | 对目标 MOD env 隐藏指定全局名 |
| `register_native(api, handler)` | 注册一个精确 Native API Handler |
| `register_rpc_observer(handler)` | 观察 Lab 捕获的 RPC 事件 |
| `register_after_run(handler)` | 在主运行完成后生成 JSON-safe 汇总 |

兼容声明 `subscribe_trace(event)` 和 `add_assertion(name, expected=...)` 会记录在扩展贡献中，但不会让 Python 扩展直接持有内部 TraceRecorder。

`context.config` 当前包含：`profile`、`runtime`、`case_id`、`mod`、`dependencies`、`scripts_zip`、`work_dir`、`report_dir`。

所有通过 `register_global` 和 after-run 返回的值都必须能够严格编码为 JSON，不能包含 `NaN`、文件句柄或任意 Python 对象。

## 5. Lua Bootstrap

可用阶段：

| 阶段 | 执行时机 |
| --- | --- |
| `pre_runtime` | Worker 基础全局建立后、通用运行时准备阶段 |
| `pre_mod` | DST `class` 和基础能力就绪后、执行目标 `modinfo.lua`/`modmain.lua` 前 |
| `post_mod` | 目标 `modmain.lua` 成功执行后 |

目录示例：

```text
modules/example_capability/
├── lua/
│   └── bootstrap.lua
├── module.toml
└── plugin.py
```

注册：

```python
def register(context):
    context.register_lua_bootstrap("pre_mod", "lua/bootstrap.lua")
```

`lua/bootstrap.lua`：

```lua
if DSTLAB_EXAMPLE_ENABLED then
    DSTLAB_EXAMPLE_STATE = { calls = 0 }
end
```

Bootstrap 仍运行在 Lab 的 Lua 隔离边界内。它不应静默伪造未知引擎效果。

## 6. Native Handler

只有在真实调用形状已经被 Trace、日志或最小 Fixture 验证后，才应新增 Native Handler。

```python
from typing import Any


def register(context: Any) -> None:
    def get_example_value(call: Any) -> str:
        call.emit(
            "example.native_call",
            "FIXTURE",
            "CAPTURED",
            argument_count=len(call.args),
        )
        return "synthetic-value"

    context.register_native("TheNet.GetExampleValue", get_example_value)
```

Handler 收到 `NativeCallContext`：

- `call.api`：精确 API 名称。
- `call.profile`：当前 Profile。
- `call.args`：Lua 传入的参数元组。
- `call.emit(...)`：写入结构化 Trace 事件。

不要注册覆盖面过大的万能 Handler。未知 API 应继续生成 `MissingNativeAPI` 和退出码 `3`。

## 7. RPC Observer 与 after-run

```python
from collections import Counter
from typing import Any


def register(context: Any) -> None:
    counts: Counter[str] = Counter()

    def observe(event: dict[str, Any]) -> None:
        counts[str(event.get("operation", "unknown"))] += 1

    def summarize(_result: dict[str, Any]) -> dict[str, Any]:
        return {"rpc_operations": dict(sorted(counts.items()))}

    context.register_rpc_observer(observe)
    context.register_after_run(summarize)
```

Observer 只接收 Lab 已捕获事件，不执行真实网络请求。after-run 输出写入 `extensions.json` 的 `after_run_outputs`。

## 8. 创建 Case Pack

最小目录：

```text
casepacks/
└── example_target/
    ├── case.toml
    ├── adapter.py
    ├── README.md
    └── tests/
        └── test_case.py
```

`case.toml`：

```toml
schema = 1
id = "example_target"
name = "Example target"
version = "1.0.0"
api_version = "1"
required_modules = ["dst_runtime_baseline", "strict_env"]
optional_modules = ["rpc_capture"]
profiles = ["modload"]
entry = "adapter.py"

[match]
required_files = ["modinfo.lua", "modmain.lua"]
```

可选的文件 Hash 匹配：

```toml
[match.file_hashes]
"modmain.lua" = ["EXPECTED_SHA256_HEX"]
```

Case 专用入口同样定义 `register(context)`。只对目标成立的适配可以放在 `adapter.py`，但通用、稳定的能力应上移为 Module。

`workshop_id` 是可选的匹配元数据。公共示例和通用 Case 不需要填写。

## 9. Case 生命周期

检查仓库内 Case：

```powershell
python dstlab.py case list
python dstlab.py case validate example_target --mod "C:\path\to\target-mod"
python dstlab.py case test example_target
```

运行指定 Case：

```powershell
python dstlab.py run `
  --profile modload `
  --case example_target `
  --mod "C:\path\to\target-mod" `
  --scripts-zip "C:\path\to\scripts.zip"
```

挂载外部 Case：

```powershell
python dstlab.py case mount "C:\path\to\example_target"
python dstlab.py case validate example_target --mod "C:\path\to\target-mod"
```

卸载并清理 Lab 内派生文件：

```powershell
python dstlab.py case unmount example_target --purge-generated
```

卸载不会删除外部 Case 源目录、原始 MOD、Workshop 内容或存档。

## 10. 测试策略

每个 Module/Case 至少覆盖：

1. Manifest 可以被 Registry 发现和校验。
2. `register(context)` 在预期 Profile 中成功执行。
3. 产生的贡献、Trace 或 after-run 输出符合契约。
4. 目标 MOD 和依赖目录在运行前后 Hash 不变。
5. 未实现 Native 仍严格失败，不被空函数吞掉。
6. 测试 Fixture 不包含账号、令牌、兑换码、真实 MOD 源码或游戏脚本。

运行完整测试：

```powershell
python -m pytest -q
```

默认测试会临时生成纯合成 `scripts.zip`。需要本机只读烟雾测试时显式设置：

```powershell
$env:DSTLAB_SCRIPTS_ZIP = "C:\path\to\scripts.zip"
$env:DSTLAB_SMOKE_MOD = "C:\path\to\target-mod"
python -m pytest -q
```

## 11. 安全边界

- 目标 MOD Lua 视为不可信输入，在独立 Worker 与受限 Lua 环境中运行。
- Module/Case 的 Python entry 是受信任的本地代码，拥有 Worker 进程的 Python 权限。不要挂载未审查的扩展。
- `context.read_bytes` 只允许读取当前扩展根目录；它不是通用文件读取接口。
- MOD/依赖文件访问必须保持只读，并限制在显式挂载根目录。
- 不在仓库中提交 `scripts.zip`、Workshop MOD、存档、日志、账号数据或运行报告。
- 观测到的调用形状、Fixture 假设和真实引擎效果应在报告与文档中明确区分。

## 12. 提交前检查

```powershell
python dstlab.py module doctor
python -m pytest -q
git status --short
git diff --check
```

确认 `work/`、`reports/` 和 `.dstlab/` 没有被强制加入暂存区，并检查新增 Fixture 中不存在本机绝对路径或目标专用秘密。
