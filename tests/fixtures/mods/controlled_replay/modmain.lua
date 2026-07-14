GLOBAL.DSTLAB_REPLAY_FIXTURE = {
    prefab_postinit = 0,
    component_postinit = 0,
    prefab_constructor = 0,
    mod_rpc = 0,
    stategraph_state = 0,
}

AddPrefabPostInit("dstlab_replay_prefab", function(inst)
    DSTLAB_REPLAY_FIXTURE.prefab_postinit = DSTLAB_REPLAY_FIXTURE.prefab_postinit + 1
    inst.replay_prefab_postinit = true
end)

AddComponentPostInit("dstlab_replay_component", function(component)
    DSTLAB_REPLAY_FIXTURE.component_postinit = DSTLAB_REPLAY_FIXTURE.component_postinit + 1
    component.replay_component_postinit = true
end)

local prefab = Prefab("dstlab_replay_prefab", function()
    DSTLAB_REPLAY_FIXTURE.prefab_constructor = DSTLAB_REPLAY_FIXTURE.prefab_constructor + 1
    local inst = CreateEntity()
    inst.prefab = "dstlab_replay_prefab"
    return inst
end)
assert(prefab.name == "dstlab_replay_prefab")

AddModRPCHandler("dstlab_replay", "ping", function(player, value)
    DSTLAB_REPLAY_FIXTURE.mod_rpc = DSTLAB_REPLAY_FIXTURE.mod_rpc + 1
    player.replay_rpc_value = value
    return value
end)

local replay_state = State({
    name = "dstlab_replay_idle",
    onenter = function(inst, data)
        DSTLAB_REPLAY_FIXTURE.stategraph_state = DSTLAB_REPLAY_FIXTURE.stategraph_state + 1
        inst.replay_state_data = data
    end,
})
AddStategraphState("dstlab_replay_graph", replay_state)

-- Registration itself must remain capture-only. The post_mod phase owns all
-- planned execution.
assert(DSTLAB_REPLAY_FIXTURE.prefab_postinit == 0)
assert(DSTLAB_REPLAY_FIXTURE.component_postinit == 0)
assert(DSTLAB_REPLAY_FIXTURE.prefab_constructor == 0)
assert(DSTLAB_REPLAY_FIXTURE.mod_rpc == 0)
assert(DSTLAB_REPLAY_FIXTURE.stategraph_state == 0)
assert(GLOBAL.DSTLAB_CONTROLLED_REPLAY_RUN == nil)
