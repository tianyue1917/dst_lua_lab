# server_sim_debug

服务端 MOD 的确定性调试 Case。它使用专用服务器角色 Fixture：

- `TheNet:GetIsServer() == true`
- `TheNet:GetIsDedicated() == true`
- `TheWorld.ismastersim == true`
- Persistence 只写入隔离内存

```powershell
python dstlab.py debug-mod --profile server-sim --mod "C:\path\to\mod" --scripts-zip "C:\path\to\scripts.zip"
```
