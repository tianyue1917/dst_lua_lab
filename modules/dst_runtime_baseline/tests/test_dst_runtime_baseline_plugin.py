from pathlib import Path
from dst_lua_lab.runtime import RuntimeAdapter

ROOT = Path(__file__).resolve().parents[1]

def test_lua_bootstrap_has_finite_entity_and_constructor_shapes():
    lua = RuntimeAdapter("lua51").create(); g = lua.globals(); g[b"GLOBAL"] = g; events=[]
    g[b"DSTLAB_NATIVE"] = lambda api,*args: events.append((api,args))
    lua.execute((ROOT/"lua"/"bootstrap.lua").read_bytes())
    out=lua.execute(b'''local p=Prefab("fixture",function() end,{Asset("ANIM","x")}); local i=CreateEntity(); i.entity:AddTransform(); i.Transform:SetPosition(1,2,3); i:AddTag("x"); return p.name,i:HasTag("x"),SpawnPrefab("child").prefab''')
    assert out == (b"fixture", True, b"child")
    assert any(args[0] == b"construct.Prefab" for _,args in events)
