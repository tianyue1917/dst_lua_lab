# general_mod_debug

通用 DST MOD 调试入口，一次启用：

- 常见 DST 构造器、世界、实体和前端形状 Fixture
- 真实 DST `constants` / `tuning` / `strings` 基础层
- MOD 和显式依赖目录内的受限只读文件访问
- DST strict MOD 环境检查
- RPC 注册与发送捕获
- 隔离的内存持久化 Fixture
- 确定性虚拟调度器

调试任意一个 MOD：

```powershell
python dstlab.py debug-mod --mod "D:\path\to\mod"
```

有显式依赖时可重复传入 `--dependency "D:\path\to\dependency"`。

它不绑定 Workshop ID 或文件 Hash，不修改目标 MOD，不访问真实网络和存档。运行结果位于 `reports/general_mod_debug/<run-id>/`。
