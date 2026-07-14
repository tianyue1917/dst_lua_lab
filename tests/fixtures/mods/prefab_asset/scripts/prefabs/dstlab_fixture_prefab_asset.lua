local assets = {
    Asset("ANIM", "anim/dstlab_fixture.zip"),
    Asset("ATLAS", "images/dstlab_fixture.xml"),
}

local dependencies = {
    "dstlab_fixture_dependency",
}

local function constructor()
    local inst = CreateEntity()
    inst.prefab = "dstlab_fixture_prefab_asset"
    inst.entity:AddTransform()
    inst.Transform:SetPosition(1, 2, 3)
    inst.entity:AddAnimState()
    inst.AnimState:SetBank("dstlab_fixture_bank")
    inst.AnimState:SetBuild("dstlab_fixture_build")
    inst.AnimState:PlayAnimation("idle", true)
    inst.entity:AddNetwork()
    inst.Network:SetPristine()
    inst:AddTag("dstlab_fixture_tag")
    return inst
end

return Prefab(
    "dstlab_fixture_prefab_asset",
    constructor,
    assets,
    dependencies
)
