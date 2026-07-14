local world = {}
DSTLAB_ATTACH_SCHEDULER(world)

local cancelled = world:DoTaskInTime(10, function(owner)
    error("a cancelled task must not execute")
end)
cancelled:Cancel()

world:DoTaskInTime(0.25, function(owner)
    assert(owner == world)
    DSTLAB_SCHEDULER_ONCE = (DSTLAB_SCHEDULER_ONCE or 0) + 1
end)

local periodic
periodic = world:DoPeriodicTask(0.5, function(owner)
    assert(owner == world)
    DSTLAB_SCHEDULER_PERIODIC = (DSTLAB_SCHEDULER_PERIODIC or 0) + 1
    if DSTLAB_SCHEDULER_PERIODIC == 2 then
        periodic:Cancel()
    end
end, 0.5)

AddPrefabPostInit("dstlab_fixture_prefab", function(inst)
    DSTLAB_ATTACH_SCHEDULER(inst)
    inst:DoTaskInTime(0, function(owner)
        assert(owner == inst)
        owner.dstlab_entity_task_ran = true
    end)
end)

DSTLAB_SCHEDULER.RunUntilIdle(20)
assert(DSTLAB_SCHEDULER_ONCE == 1)
assert(DSTLAB_SCHEDULER_PERIODIC == 2)
assert(DSTLAB_SCHEDULER.PendingCount() == 0)
