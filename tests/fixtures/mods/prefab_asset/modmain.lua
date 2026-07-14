PrefabFiles = {
    "dstlab_fixture_prefab_asset",
}

Assets = {
    Asset("ATLAS", "images/dstlab_fixture.xml"),
    Asset("IMAGE", "images/dstlab_fixture.tex"),
}

local prefab = modimport("scripts/prefabs/dstlab_fixture_prefab_asset.lua")
assert(prefab.name == "dstlab_fixture_prefab_asset")
assert(#prefab.assets == 2)
assert(prefab.deps[1] == "dstlab_fixture_dependency")

-- The Lab never starts prefab constructors implicitly. Explicit invocation is
-- a controlled Fixture action which validates the returned entity shape.
local inst = prefab.fn()
assert(inst.prefab == "dstlab_fixture_prefab_asset")
assert(inst:HasTag("dstlab_fixture_tag"))
assert(inst.Transform ~= nil)
assert(inst.AnimState ~= nil)
assert(inst.Network.pristine == true)
local x, y, z = inst.Transform:GetWorldPosition()
assert(x == 1 and y == 2 and z == 3)
