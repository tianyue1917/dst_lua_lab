-- In DST's strict MOD environment engine globals are reached through GLOBAL;
-- they are not all silently inherited as bare names.
GLOBAL.assert(pcall == nil, "strict MOD env leaked bare pcall")
GLOBAL.assert(GLOBAL.type(GLOBAL.pcall) == "function")
GLOBAL.assert(GLOBAL ~= env)

STRICT_ENV_FIXTURE_OK = true
