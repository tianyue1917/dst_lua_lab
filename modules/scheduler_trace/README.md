# scheduler_trace

提供确定性虚拟时间队列，时间不会自动流逝。Case Probe 可以显式推进：

```lua
local inst = DSTLAB_ATTACH_SCHEDULER({})
inst:DoTaskInTime(2, function(owner) owner.ready = true end)
DSTLAB_SCHEDULER.Advance(2)
assert(inst.ready == true)
```

支持 `DoTaskInTime`、`DoPeriodicTask`、`Cancel`、`Advance`和 `RunUntilIdle`。默认最多执行 10000 步，避免周期任务无限循环。模块不读取墙上时钟。
