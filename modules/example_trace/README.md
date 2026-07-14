# Synthetic trace example

`example_trace` 是一个不对应任何真实 MOD 的 Capability Module 示例。它只用于说明：

- Module 的清单与目录名如何对应；
- Case Pack 如何通过 `required_modules` 请求通用能力；
- 扩展入口只应由隔离 Worker 加载。

`module list`、`module doctor` 和依赖解析只读取 `module.toml`，不会导入
`plugin.py`。具体 `run` 启动隔离 Worker 后，计划中选中的入口才会执行
`register(context)`。

`register(context)` 使用受限、版本化的 Extension API；`subscribe_trace` 只记录
声明，不会把内部 TraceRecorder、CLI 或任意宿主文件系统对象交给扩展。
