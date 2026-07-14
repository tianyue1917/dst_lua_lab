# strict_env

更接近 DST 的 MOD 环境：默认使裸 `pcall` / `xpcall` 访问为 `nil`，因此错误的直接调用会当场失败；同时 `GLOBAL` 本身仍保留完整全局表，可使用：

```lua
local pcall = GLOBAL.rawget(GLOBAL, "pcall")
```

这个模块不修改 MOD 源码。默认名单刻意很小；未经真实 DST 运行时验证，不应随意扩大禁止范围。
