# frontend_mod_debug

客户端与 UI MOD 的确定性调试 Case。它使用客户端角色 Fixture：

- `TheNet:GetIsClient() == true`
- `TheWorld.ismastersim == false`
- 合成 `ThePlayer`、`TheInput`、`TheFrontEnd`
- 不访问真实网络、渲染器、账号或客户端存档

```powershell
python dstlab.py debug-mod --profile frontend --mod "C:\path\to\mod" --scripts-zip "C:\path\to\scripts.zip"
```
