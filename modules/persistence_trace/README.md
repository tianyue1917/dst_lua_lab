# persistence_trace

为常用 `TheSim` 持久化 API 提供进程内存 Fixture，并记录读、写、删除。数据仅在当次 Worker 进程存活；模块不读写 Klei 存档、Workshop 目录或其他真实文件。

当前每次运行从空 Fixture 开始，未命中的读取按 DST 回调语义返回 `false, nil`。模块 API 已预留 `initial` 映射，待 Case Manifest 开放声明式配置后可以无需改代码接入。
