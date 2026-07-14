-- Capture callback registrations without invoking them. Replay is exposed only
-- through a closure consumed by the post_mod bootstrap.
local plan = GLOBAL.DSTLAB_REPLAY_PLAN or {}
local trusted_native = DSTLAB_NATIVE
local trusted_xpcall = GLOBAL.xpcall
local trusted_create_entity = GLOBAL.CreateEntity
local registry = {
    prefab_postinit = {},
    component_postinit = {},
    prefab_constructor = {},
    mod_rpc = { server = {}, client = {}, shard = {} },
    stategraph_state = {},
}

local function emit(operation, index, kind, status, target, callback, detail)
    return trusted_native(
        "DSTLab.ControlledReplay.Event",
        operation,
        index or 0,
        kind or "",
        status or "captured",
        target or "",
        callback or "",
        detail or ""
    )
end

local function append(bucket, key, callback)
    local callbacks = bucket[key]
    if callbacks == nil then
        callbacks = {}
        bucket[key] = callbacks
    end
    table.insert(callbacks, callback)
end

local function install(name, capture)
    local original = GLOBAL[name]
    -- Worker host functions appear as callable userdata under Lupa, while
    -- baseline-provided constructors are ordinary Lua functions.
    assert(
        type(original) == "function" or type(original) == "userdata",
        "controlled_replay requires callable " .. name
    )
    local wrapped = function(...)
        capture(...)
        return original(...)
    end
    GLOBAL[name] = wrapped
    if env ~= nil then env[name] = wrapped end
end

install("AddPrefabPostInit", function(target, callback)
    if type(target) == "string" and type(callback) == "function" then
        append(registry.prefab_postinit, target, callback)
        emit("capture", 0, "prefab_postinit", "captured", target, "postinit", "registration")
    end
end)

install("AddComponentPostInit", function(target, callback)
    if type(target) == "string" and type(callback) == "function" then
        append(registry.component_postinit, target, callback)
        emit("capture", 0, "component_postinit", "captured", target, "postinit", "registration")
    end
end)

install("Prefab", function(target, callback)
    if type(target) == "string" and type(callback) == "function" then
        append(registry.prefab_constructor, target, callback)
        emit("capture", 0, "prefab_constructor", "captured", target, "constructor", "registration")
    end
end)

local rpc_api = {
    AddModRPCHandler = "server",
    AddClientModRPCHandler = "client",
    AddShardModRPCHandler = "shard",
}
for api, rpc_type in pairs(rpc_api) do
    install(api, function(namespace, name, callback)
        if type(namespace) == "string" and type(name) == "string" and type(callback) == "function" then
            local key = namespace .. "\0" .. name
            append(registry.mod_rpc[rpc_type], key, callback)
            emit("capture", 0, "mod_rpc", "captured", namespace .. "." .. name, rpc_type, "registration")
        end
    end)
end

local function capture_state(stategraph, state)
    if type(stategraph) ~= "string" or type(state) ~= "table" or type(state.name) ~= "string" then
        return
    end
    local graph = registry.stategraph_state[stategraph]
    if graph == nil then
        graph = {}
        registry.stategraph_state[stategraph] = graph
    end
    graph[state.name] = state
    emit("capture", 0, "stategraph_state", "captured", stategraph .. "." .. state.name, "state", "registration")
end

local function capture_states(stategraph, states)
    if type(states) ~= "table" then return end
    for _, state in ipairs(states) do capture_state(stategraph, state) end
end

install("StateGraph", function(name, states)
    capture_states(name, states)
end)

install("AddStategraph", function(name, states)
    capture_states(name, states)
end)

install("AddStategraphState", function(name, state)
    capture_state(name, state)
end)

local unpack_args = table.unpack or unpack

local function copy_fields(target, fields)
    if type(fields) ~= "table" then return end
    for key, value in pairs(fields) do target[key] = value end
end

local function make_entity(spec, fallback_prefab)
    spec = type(spec) == "table" and spec or {}
    local inst = trusted_create_entity()
    assert(type(inst) == "table", "CreateEntity fixture must return a table")
    inst.prefab = spec.prefab or fallback_prefab or "dstlab_replay_fixture"
    copy_fields(inst, spec.fields)
    if type(spec.tags) == "table" then
        for _, tag in ipairs(spec.tags) do
            if type(tag) == "string" then inst:AddTag(tag) end
        end
    end
    if type(spec.components) == "table" then
        for name, fields in pairs(spec.components) do
            if type(name) == "string" then
                local component = inst.components ~= nil and inst.components[name] or nil
                if component == nil then component = inst:AddComponent(name) end
                copy_fields(component, fields)
            end
        end
    end
    if type(spec.position) == "table" then
        if inst.Transform == nil then inst:AddTransform() end
        inst.Transform:SetPosition(spec.position[1] or 0, spec.position[2] or 0, spec.position[3] or 0)
    end
    return inst
end

local function make_stategraph_fixture(inst, graph_name, state_name)
    local controller = {
        name = graph_name,
        mem = {},
        statemem = {},
        currentstate = { name = state_name, tags = {} },
    }
    function controller:GoToState(name, data)
        self.last_transition = { name = name, data = data }
    end
    function controller:SetTimeout(timeout) self.timeout = timeout end
    function controller:HasStateTag(tag)
        return self.currentstate.tags[tag] == true
    end
    inst.sg = controller
    return inst
end

local function call_with(fn, prefix, args)
    local values = {}
    for _, value in ipairs(prefix or {}) do table.insert(values, value) end
    for _, value in ipairs(args or {}) do table.insert(values, value) end
    return fn(unpack_args(values, 1, #values))
end

local function callback_outcome(index, item, target, callback_name, fn, prefix)
    local ok, result = trusted_xpcall(
        function() return call_with(fn, prefix, item.args) end,
        function(err) return tostring(err) end
    )
    if ok then
        emit("callback", index, item.kind, "executed", target, callback_name, "return_type=" .. type(result))
    else
        emit("callback", index, item.kind, "failed", target, callback_name, result)
    end
    return ok, result
end

local function missing(index, item, target, callback_name, detail)
    local status = item.strict == true and "failed" or "skipped"
    emit("item", index, item.kind, status, target, callback_name, detail)
    if item.strict == true then
        error("controlled replay strict item " .. index .. " failed: " .. detail, 0)
    end
    return false
end

local function run_callbacks(index, item, target, callback_name, callbacks, prefix_factory)
    if type(callbacks) ~= "table" or #callbacks == 0 then
        return missing(index, item, target, callback_name, "matching registration not found")
    end
    local all_ok = true
    for callback_index, callback in ipairs(callbacks) do
        local prefix = prefix_factory ~= nil and prefix_factory(callback_index) or {}
        local ok, detail = callback_outcome(index, item, target, callback_name, callback, prefix)
        if not ok then
            all_ok = false
            if item.strict == true then
                emit("item", index, item.kind, "failed", target, callback_name, detail)
                error("controlled replay strict callback failed: " .. tostring(detail), 0)
            end
        end
    end
    emit(
        "item",
        index,
        item.kind,
        all_ok and "executed" or "failed",
        target,
        callback_name,
        "callbacks=" .. tostring(#callbacks)
    )
    return all_ok
end

local function state_callback(item, state)
    local callback_name = item.callback or "onenter"
    if callback_name == "timeline" then
        local event = type(state.timeline) == "table" and state.timeline[item.timeline_index or 1] or nil
        return event ~= nil and event.fn or nil
    end
    if callback_name == "event" then
        for _, event in ipairs(state.events or {}) do
            if event.name == item.event then return event.fn end
        end
        return nil
    end
    return state[callback_name]
end

local function run_item(index, item)
    local kind = item.kind
    if kind == "prefab_postinit" then
        local target = item.target
        local inst = nil
        return run_callbacks(index, item, target, "postinit", registry.prefab_postinit[target], function()
            if inst == nil then inst = make_entity(item.entity, target) end
            return { inst }
        end)
    elseif kind == "component_postinit" then
        local target = item.target
        local component = nil
        return run_callbacks(index, item, target, "postinit", registry.component_postinit[target], function()
            if component == nil then
                local inst = make_entity(item.entity, "dstlab_component_owner")
                component = inst.components ~= nil and inst.components[target] or nil
                if component == nil then component = inst:AddComponent(target) end
                copy_fields(component, item.component)
            end
            return { component }
        end)
    elseif kind == "prefab_constructor" then
        local target = item.target
        return run_callbacks(index, item, target, "constructor", registry.prefab_constructor[target], nil)
    elseif kind == "mod_rpc" then
        local rpc_type = item.rpc_type or "server"
        local target = item.namespace .. "." .. item.name
        local callbacks = registry.mod_rpc[rpc_type][item.namespace .. "\0" .. item.name]
        local rpc_context = nil
        return run_callbacks(index, item, target, rpc_type, callbacks, function()
            if rpc_type == "server" then
                if rpc_context == nil then
                    rpc_context = make_entity(item.player or item.entity, "dstlab_rpc_player")
                end
                return { rpc_context }
            elseif rpc_type == "shard" then
                return { item.shard_id or "DSTLAB_OFFLINE_SHARD" }
            end
            return {}
        end)
    elseif kind == "stategraph_state" then
        local target = item.stategraph .. "." .. item.state
        local graph = registry.stategraph_state[item.stategraph]
        local state = graph ~= nil and graph[item.state] or nil
        if state == nil then
            return missing(index, item, target, item.callback or "onenter", "matching state registration not found")
        end
        local callback_name = item.callback or "onenter"
        local callback = state_callback(item, state)
        if type(callback) ~= "function" then
            return missing(index, item, target, callback_name, "matching state callback not found")
        end
        local inst = make_stategraph_fixture(
            make_entity(item.entity, "dstlab_stategraph_owner"),
            item.stategraph,
            item.state
        )
        local ok, detail = callback_outcome(index, item, target, callback_name, callback, { inst })
        emit("item", index, kind, ok and "executed" or "failed", target, callback_name, ok and "callbacks=1" or detail)
        if not ok and item.strict == true then
            error("controlled replay strict callback failed: " .. tostring(detail), 0)
        end
        return ok
    end
    return missing(index, item, tostring(kind), "", "unsupported replay kind")
end

-- Keep the plan and callback registry inside this closure. No plan means the
-- post_mod phase returns immediately and no registered callback can execute.
local consumed = false
local function run_once()
    if consumed then error("controlled replay runner was already consumed", 0) end
    consumed = true
    if type(plan) ~= "table" or #plan == 0 then return 0 end
    emit("plan", 0, "controlled_replay", "started", "", "", "items=" .. tostring(#plan))
    local completed = 0
    for index, item in ipairs(plan) do
        run_item(index, item)
        completed = completed + 1
    end
    emit("plan", 0, "controlled_replay", "finished", "", "", "items=" .. tostring(completed))
    return completed
end

-- Do not expose the mutable plan to modmain. The worker-owned after-run report
-- retains the authoritative JSON copy.
GLOBAL.DSTLAB_REPLAY_PLAN = nil
if env ~= nil then env.DSTLAB_REPLAY_PLAN = nil end
return run_once
