# dst_runtime_baseline

提供有形状、可追踪、不冒充真引擎的 DST Fixture：`Asset` / `Prefab` / `Recipe` / `Ingredient` / `Action`、StateGraph 数据构造器、官方 `Class` 优先的后备、`CreateEntity` / `SpawnPrefab`、GUID、Tag、组件与事件容器、有限的 `Transform` / `AnimState` / `Network` 等子系统，以及 `TheWorld` / `TheNet` / `TheInput` / `TheFrontEnd`。

`modload`、`frontend`、`server-sim` 分别使用 hosted、客户端、专用服务器角色。客户端角色提供合成 `ThePlayer`；`KnownModIndex` 只实现当前显式 MOD/依赖列表和已执行 `modinfo.lua` 可以证明的查询，其他方法继续进入严格 Missing Native 报告。受限 `io.open` 对写模式和挂载根目录外路径生成明确的拒绝 Trace。

所有 Fixture 效果记录为 `type=runtime.fixture source=FIXTURE effect=CAPTURED`，并在 `extensions.json` 汇总。未实现的方法保持 `nil`，不使用万能成功 Stub。这些形状只证明 MOD 的构造、注册和状态变化，不证明真实渲染、物理、网络或服务器执行。
