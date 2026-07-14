assert(DSTLAB_ROLE.profile == DSTLAB_PROFILE)

if DSTLAB_PROFILE == "frontend" then
    assert(TheWorld.ismastersim == false)
    assert(TheWorld.ismastershard == false)
    assert(TheNet:GetIsServer() == false)
    assert(TheNet:GetIsClient() == true)
    assert(TheNet:GetIsDedicated() == false)
    assert(ThePlayer ~= nil and ThePlayer:HasTag("player"))
elseif DSTLAB_PROFILE == "server-sim" then
    assert(TheWorld.ismastersim == true)
    assert(TheWorld.ismastershard == true)
    assert(TheNet:GetIsServer() == true)
    assert(TheNet:GetIsClient() == false)
    assert(TheNet:GetIsDedicated() == true)
    assert(TheNet:GetServerIsClientHosted() == false)
else
    assert(DSTLAB_PROFILE == "modload")
    assert(TheNet:GetIsServer() == true)
    assert(TheNet:GetIsDedicated() == false)
end
