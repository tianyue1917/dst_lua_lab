-- Deterministic virtual scheduler. Time advances only when Advance/RunUntilIdle
-- is explicitly invoked by a Case probe.
local scheduler = {
    now = 0,
    next_id = 1,
    queue = {},
}

local function emit(name, ...)
    return DSTLAB_NATIVE("DSTLab.Scheduler.Event", name, ...)
end

local function sort_queue()
    table.sort(scheduler.queue, function(a, b)
        if a.at == b.at then return a.id < b.id end
        return a.at < b.at
    end)
end

local function schedule(delay, fn, period, owner)
    assert(type(delay) == "number" and delay >= 0, "delay must be a non-negative number")
    assert(type(fn) == "function", "task callback must be a function")
    local task = {
        id = scheduler.next_id,
        at = scheduler.now + delay,
        fn = fn,
        period = period,
        owner = owner,
        cancelled = false,
    }
    scheduler.next_id = scheduler.next_id + 1
    function task:Cancel()
        if not self.cancelled then
            self.cancelled = true
            emit("cancel", self.id, scheduler.now)
        end
    end
    function task:IsCancelled() return self.cancelled end
    table.insert(scheduler.queue, task)
    sort_queue()
    emit(period == nil and "schedule" or "schedule_periodic", task.id, task.at)
    return task
end

function scheduler.Schedule(delay, fn, owner)
    return schedule(delay, fn, nil, owner)
end

function scheduler.SchedulePeriodic(delay, period, fn, owner)
    assert(type(period) == "number" and period > 0, "period must be a positive number")
    return schedule(delay, fn, period, owner)
end

function scheduler.Advance(delta, max_steps)
    assert(type(delta) == "number" and delta >= 0, "delta must be a non-negative number")
    local target = scheduler.now + delta
    local limit = max_steps or 10000
    local steps = 0
    while true do
        sort_queue()
        local task = scheduler.queue[1]
        if task == nil or task.at > target then break end
        table.remove(scheduler.queue, 1)
        scheduler.now = task.at
        if not task.cancelled then
            steps = steps + 1
            if steps > limit then error("DSTLab scheduler max_steps exceeded", 2) end
            emit("run", task.id, scheduler.now)
            task.fn(task.owner)
            if task.period ~= nil and not task.cancelled then
                task.at = scheduler.now + task.period
                table.insert(scheduler.queue, task)
            end
        end
    end
    scheduler.now = target
    return steps
end

function scheduler.RunUntilIdle(max_steps)
    local limit = max_steps or 10000
    local steps = 0
    while #scheduler.queue > 0 do
        sort_queue()
        local delta = math.max(0, scheduler.queue[1].at - scheduler.now)
        steps = steps + scheduler.Advance(delta, limit - steps)
        if steps >= limit and #scheduler.queue > 0 then
            error("DSTLab scheduler max_steps exceeded", 2)
        end
    end
    return steps
end

function scheduler.PendingCount()
    local count = 0
    for _, task in ipairs(scheduler.queue) do
        if not task.cancelled then count = count + 1 end
    end
    return count
end

local function attach(inst)
    assert(type(inst) == "table", "scheduler owner must be a table")
    if inst.DoTaskInTime == nil then
        function inst:DoTaskInTime(delay, fn)
            return scheduler.Schedule(delay, fn, self)
        end
    end
    if inst.DoPeriodicTask == nil then
        function inst:DoPeriodicTask(period, fn, initialdelay)
            return scheduler.SchedulePeriodic(initialdelay or period, period, fn, self)
        end
    end
    return inst
end

GLOBAL.DSTLAB_SCHEDULER = scheduler
GLOBAL.DSTLAB_ATTACH_SCHEDULER = attach

if type(GLOBAL.EntityScript) == "table" then
    attach(GLOBAL.EntityScript)
end
