# Synthetic trace example

`example_trace` 是一个不对应任何真实 MOD 的 Capability Module 示例。它只用于说明：

- Module 的清单与目录名如何对应；
- Case Pack 如何通过 `required_modules` 请求通用能力；
- 扩展入口只应由隔离 Worker 加载。

当前第一阶段是 `management_only`。`module list`、`module doctor` 和依赖解析只读取
`module.toml`，不会导入 `plugin.py`；因此这个入口目前不会生效。

后续 Worker Extension API 落地后，`register(context)` 中使用的
`subscribe_trace` 也必须是受限、版本化 API，不能获得 CLI 或宿主文件系统对象。
