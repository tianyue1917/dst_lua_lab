local shared_first = require("shared.fixture")
local shared_second = require("shared.fixture")

assert(shared_first == shared_second, "dependency require must be cached")
assert(shared_first.origin == "synthetic_dependency")
assert(shared_first.value == 73)
