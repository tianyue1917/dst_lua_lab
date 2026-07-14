local read_callback_called = false
TheSim:GetPersistentString("dstlab_fixture_profile", function(success, data)
    assert(success == false)
    assert(data == nil)
    read_callback_called = true
end)
assert(read_callback_called, "read callback must run deterministically")

local write_callback_called = false
TheSim:SetPersistentString(
    "dstlab_fixture_profile",
    "fixture\0payload",
    false,
    function(success)
        assert(success == true)
        write_callback_called = true
    end
)
assert(write_callback_called, "write callback must run deterministically")
