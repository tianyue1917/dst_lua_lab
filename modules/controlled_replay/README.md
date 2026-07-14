# controlled_replay

`controlled_replay` 在 MOD 完成加载后，按显式 JSON 计划回放少量已注册回调。它依赖
`dst_runtime_baseline`，只使用有限的合成实体、虚拟玩家和虚拟 StateGraph 控制器；不访问网络、
存档、渲染、物理或真实 DST 服务端。

## 安全语义

- **默认只捕获，不执行**：未提供计划时不会加载该 Module；显式空计划会加载捕获层，但任何已注册回调都不会执行。
- **只按精确目标执行**：找不到目标时，普通条目记为 `skipped`；`strict: true` 条目记录失败后抛错。
- **Runner 不暴露给 MOD**：`pre_mod` Bootstrap 返回 Worker 私有、单次消费的回调；目标 `modmain.lua` 不能提前调用、替换或重复执行它。
- **不冒充真实引擎**：成功只表示回调在合成数据形状上运行完毕，不证明游戏内效果成立。
- **结果可审计**：`trace.jsonl` 中事件类型为 `replay.*`，`extensions.json` 中包含逐项汇总。

## 计划格式

计划文件的根必须是 JSON 数组。当前支持以下 `kind`：

```json
[
  {
    "kind": "prefab_postinit",
    "target": "example_item",
    "entity": {"tags": ["inventoryitem"], "fields": {"fixture_value": 1}},
    "strict": true
  },
  {
    "kind": "component_postinit",
    "target": "health",
    "component": {"currenthealth": 100}
  },
  {
    "kind": "prefab_constructor",
    "target": "example_item"
  },
  {
    "kind": "mod_rpc",
    "rpc_type": "server",
    "namespace": "example_namespace",
    "name": "ping",
    "args": ["payload"],
    "player": {"fields": {"userid": "DSTLAB_OFFLINE_USER"}}
  },
  {
    "kind": "stategraph_state",
    "stategraph": "wilson",
    "state": "example_idle",
    "callback": "onenter",
    "args": [{"reason": "fixture"}]
  }
]
```

StateGraph `callback` 可选 `onenter`、`onexit`、`onupdate`、`ontimeout`、`timeline` 或
`event`。`timeline` 可用 `timeline_index`（从 1 开始）；`event` 必须提供 `event` 名称。

合成实体字段：

- `prefab`：实体名；
- `fields`：直接写入实体的 JSON 字段；
- `tags`：通过 `AddTag` 添加的字符串数组；
- `components`：组件名到字段对象的映射；
- `position`：`[x, y, z]`，使用基线 `Transform` Fixture。

启用模块并将计划交给 CLI（具体入口参见项目根 README）：

```powershell
python dstlab.py run --profile modload --module controlled_replay `
  --mod C:\path\to\mod --scripts-zip C:\path\to\scripts.zip `
  --replay-plan C:\path\to\replay-plan.json
```

建议先不带计划运行一次，检查注册报告；再一次只增加一个计划条目。不要把包含本机路径或私有
数据的计划文件提交到仓库。
