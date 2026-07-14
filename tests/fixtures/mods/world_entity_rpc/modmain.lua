assert(TheWorld.ismastersim == true)
assert(TheWorld.ismastershard == true)
TheWorld:AddTag("dstlab_fixture_world")
assert(TheWorld:HasTag("dstlab_fixture_world"))

assert(TheNet:GetIsServer() == true)
assert(TheNet:GetIsClient() == false)
assert(TheNet:GetIsDedicated() == false)
assert(TheNet:GetServerIsClientHosted() == true)
assert(TheInput:IsKeyDown(1) == false)
assert(TheInput:GetWorldPosition().x == 0)

local screen = { name = "dstlab_fixture_screen" }
TheFrontEnd:PushScreen(screen)
assert(TheFrontEnd:GetActiveScreen() == screen)
assert(TheFrontEnd:PopScreen() == screen)

local inst = CreateEntity()
inst.prefab = "dstlab_fixture_entity"
inst.entity:AddTransform()
inst.Transform:SetPosition(4, 5, 6)
inst:AddTag("dstlab_fixture_entity_tag")
assert(inst:HasTag("dstlab_fixture_entity_tag"))
local component = inst:AddComponent("dstlab_fixture_component")
assert(component.inst == inst)
assert(inst:GetComponent("dstlab_fixture_component") == component)

local event_seen = false
inst:ListenForEvent("dstlab_fixture_event", function(owner, data)
    assert(owner == inst)
    assert(data.value == 9)
    event_seen = true
end)
inst:PushEvent("dstlab_fixture_event", { value = 9 })
assert(event_seen == true)

local child = SpawnPrefab("dstlab_fixture_child")
assert(child.prefab == "dstlab_fixture_child")
assert(child.GUID ~= inst.GUID)

AddModRPCHandler("dstlab_fixture", "server", function() end)
AddClientModRPCHandler("dstlab_fixture", "client", function() end)
AddShardModRPCHandler("dstlab_fixture", "shard", function() end)

local server_rpc = GetModRPC("dstlab_fixture", "server")
local client_rpc = GetClientModRPC("dstlab_fixture", "client")
local shard_rpc = GetShardModRPC("dstlab_fixture", "shard")
assert(server_rpc == MOD_RPC.dstlab_fixture.server)
assert(client_rpc == CLIENT_MOD_RPC.dstlab_fixture.client)
assert(shard_rpc == SHARD_MOD_RPC.dstlab_fixture.shard)
assert(server_rpc.id == "dstlab_fixture.server" and server_rpc.kind == "server")
assert(client_rpc.kind == "client" and shard_rpc.kind == "shard")

-- rpc_capture replaces these with local observers. No handler or network peer
-- is contacted by any call below.
SendModRPCToServer(server_rpc, "payload")
SendModRPCToClient(client_rpc, "fixture_player", "payload")
SendModRPCToShard(shard_rpc, "fixture_shard", "payload")
SendClientModRPCToServer(client_rpc, "payload")
