-- Observe outbound RPC calls. The host bridge records arguments but never
-- opens a socket or claims that a remote handler executed.
local function wrap_sender(name)
    local original = GLOBAL[name]
    local function wrapped(...)
        DSTLAB_RPC_OBSERVE("send", name, ...)
        if original ~= nil then
            return original(...)
        end
        return nil
    end
    GLOBAL[name] = wrapped
end

wrap_sender("SendModRPCToServer")
wrap_sender("SendModRPCToClient")
wrap_sender("SendModRPCToShard")
wrap_sender("SendClientModRPCToServer")
