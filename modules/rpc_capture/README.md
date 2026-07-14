# rpc_capture

捕获 `Add*ModRPCHandler` 注册与 `Send*ModRPC*` 发送边界。模块只生成本地 Trace，不访问网络，也不把“已捕获发送”误报为“服务端已执行”。

用法：

```powershell
python dstlab.py run --profile modload --module rpc_capture --mod <MOD> --scripts-zip <scripts.zip>
```

决定性证据在 `trace.jsonl` 和 `extensions.json` 中。
