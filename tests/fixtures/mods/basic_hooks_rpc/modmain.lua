local first = require("fixture.helper")
local second = require("fixture.helper")
assert(first == second, "require must cache a module result")
assert(first.answer == 42)

modimport("scripts/imported.lua")
assert(DSTLAB_IMPORTED_VALUE == "imported")

AddPrefabPostInit("dstlab_fixture_prefab", function(inst)
    inst.dstlab_prefab_hook = true
end)

AddComponentPostInit("dstlab_fixture_component", function(component)
    component.dstlab_component_hook = true
end)

AddClassPostConstruct("widgets/dstlab_fixture", function(widget)
    widget.dstlab_widget_hook = true
end)

AddPlayerPostInit(function(player)
    player.dstlab_player_hook = true
end)

AddModRPCHandler("dstlab_fixture", "server_ping", function(player, value)
    return value
end)

AddClientModRPCHandler("dstlab_fixture", "client_ping", function(value)
    return value
end)

AddShardModRPCHandler("dstlab_fixture", "shard_ping", function(shard_id, value)
    return value
end)

-- These functions exist only when rpc_capture is enabled. The wrapper records
-- the send boundary and deliberately performs no network delivery.
if GLOBAL.SendModRPCToServer ~= nil then
    SendModRPCToServer("dstlab_server_handle", "fixture_payload")
    SendModRPCToClient("dstlab_client_handle", "fixture_player", "fixture_payload")
    SendModRPCToShard("dstlab_shard_handle", "fixture_shard", "fixture_payload")
    SendClientModRPCToServer("dstlab_client_server_handle", "fixture_payload")
end
