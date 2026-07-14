# Synthetic Case Pack

`example_case` 是生命周期测试和文档使用的纯合成 Case Pack。它不包含 Workshop
ID、账号、兑换码、目标 Hash 或真实 MOD 文件。

它声明 `example_trace` 为必需 Module，用于证明 Case 选择时会自动把依赖纳入
`ExtensionPlan`。此自动解析不等同于在 `.dstlab/state.json` 中永久启用 Module。

`list`、`validate`、`doctor` 只读取 Manifest，不导入 `adapter.py`。使用
`run --case example_case` 时，隔离 Worker 会校验计划 Hash 后执行
`register(context)` 并记录声明式断言贡献。

典型流程：

```powershell
python dstlab.py module list
python dstlab.py case list
python dstlab.py case validate example_case
python dstlab.py run --case example_case --source "return 42"
python dstlab.py case clean example_case
```

外部 Case Pack 应使用 `case mount <path>` 注册，用 `case unmount <id>` 移除。
卸载只移除挂载状态；`--purge-generated` 也只能清理该 Case 的 `work/` 与
`reports/` 命名空间，不会删除外部 Case Pack 源目录。
