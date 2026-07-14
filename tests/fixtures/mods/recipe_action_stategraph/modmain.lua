local callback_ran = false
local ingredients = {
    Ingredient("twigs", 2),
    Ingredient("cutgrass", 1, "images/inventoryimages.xml"),
}
assert(ingredients[1].type == "twigs" and ingredients[1].amount == 2)

local legacy = Recipe(
    "dstlab_fixture_legacy_recipe",
    ingredients,
    nil,
    TECH.NONE,
    nil,
    nil,
    true
)
assert(legacy.product == "dstlab_fixture_legacy_recipe")

local modern = AddRecipe2(
    "dstlab_fixture_recipe",
    ingredients,
    TECH.NONE,
    { nounlock = true },
    { "TOOLS" }
)
assert(AllRecipes.dstlab_fixture_recipe == modern)

local constructed_action = Action({
    id = "DSTLAB_CONSTRUCTED_ACTION",
    str = "Synthetic action",
    fn = function()
        callback_ran = true
        return true
    end,
})
assert(constructed_action.id == "DSTLAB_CONSTRUCTED_ACTION")

local registered_action = AddAction(
    "DSTLAB_REGISTERED_ACTION",
    "Synthetic registered action",
    function()
        callback_ran = true
        return true
    end
)
assert(ACTIONS.DSTLAB_REGISTERED_ACTION == registered_action)

AddComponentAction("SCENE", "dstlab_fixture_component", function()
    callback_ran = true
end)

local idle = State({
    name = "dstlab_idle",
    timeline = {
        TimeEvent(0.5, function()
            callback_ran = true
        end),
    },
})
local attacked = EventHandler("attacked", function()
    callback_ran = true
end)
local action_handler = ActionHandler(constructed_action, "dstlab_idle")
local graph = StateGraph(
    "dstlab_fixture_graph",
    { idle },
    { attacked },
    "dstlab_idle",
    { action_handler }
)
assert(graph.initialstate == "dstlab_idle")

AddStategraph("dstlab_fixture_graph", { idle }, { attacked }, "dstlab_idle")
AddStategraphState("dstlab_fixture_graph", idle)
AddStategraphEventHandler("dstlab_fixture_graph", attacked)

assert(callback_ran == false, "capture-only registrations must not run callbacks")
