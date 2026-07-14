assert(KnownModIndex:GetModActualName(modname) == modname)
assert(KnownModIndex:IsModEnabled(modname) == true)
assert(KnownModIndex:DoesModExist(modname) == true)
local mods = KnownModIndex:GetModsToLoad()
assert(mods[1] == modname)
for _, name in ipairs(mods) do
    assert(KnownModIndex:IsModEnabled(name) == true)
    assert(KnownModIndex:DoesModExist(name) == true)
end
assert(KnownModIndex:IsModEnabled("not_loaded_dependency") == false)
local info = KnownModIndex:GetModInfo(modname)
assert(info.name == "DST Lab KnownModIndex Fixture")
assert(KnownModIndex.savedata.known_mods[modname].modinfo == info)
assert(KnownModIndex:GetModInfo("synthetic_dependency") == nil)
