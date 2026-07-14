# Modload synthetic corpus and coverage gaps

This directory contains only invented, offline fixtures. It must not contain a
real account identifier, Workshop identifier, network endpoint, or save path.
Every persistence operation targets the Lab's isolated in-memory backend.

## Corpus

| Fixture | Boundary under test | Expected evidence |
| --- | --- | --- |
| `basic_hooks_rpc` | `require` cache, `modimport`, common post-init hooks, server/client/shard RPC registration | `modules.json`, `hooks.json`, `rpc.json`, `rpc_capture` summary |
| `persistence` | missing read followed by a binary-safe write and synchronous callbacks | `persistence.json`, `persistence_trace` isolated-backend summary |
| `scheduler_entity` | cancellable one-shot and periodic entity tasks under explicit virtual-time advancement | `scheduler_trace` events, no wall-clock access |
| `strict_env` | bare `pcall`/`xpcall` denial while `GLOBAL` remains available | `strict_env` summary and successful mod entry |
| `cross_mod_target` + `cross_mod_dependency` | declared dependency resolution, provenance, and require caching | `modules.json` with `dependency_0` and `dep://0/` provenance |
| `prefab_asset` | capture-only `Asset`/`Prefab` descriptors plus entity subsystem shapes | `registrations.json`, `dst_runtime_baseline` summary |
| `recipe_action_stategraph` | recipe, action and stategraph declarations without callback execution | structured registration contracts |
| `world_entity_rpc` | world/entity/tag/event/RPC identity and offline sends | fixture events and `network_access=false` |
| `world_unknown_native` | strict fallback for an unknown `TheNet` method | exit 3 and `unsupported.json` |
| `scoped_io` | read-only access inside the selected MOD root | file-read trace, unchanged source tree, rejected write |
| `profile_roles` | distinct frontend and dedicated server role fixtures | profile-specific world/net/player assertions |
| `known_mod_index` | selected MOD identity and read-only modinfo queries | traceable `KnownModIndex` events |
| `controlled_replay` | five explicit callback replay kinds | no implicit execution, replay trace and after-run summary |

The integration contract is in
`tests/integration/test_modload_fixture_corpus.py`. The Worker now advertises
extension execution, so `extensions.json` and every behavioral assertion are
required; the suite no longer hides a missing extension runtime behind xfail.

## What the minimal Modload profile already proves

- `modinfo.lua` and `modmain.lua` execute from the read-only VFS.
- Official scripts, target scripts, and explicitly declared dependencies have
  auditable URI and SHA-256 provenance.
- `require` caches results; `modimport` executes in the target MOD environment.
- Common Hook/RPC/Prefab/Asset/Recipe/Action/Stategraph/atlas registrations are
  captured with explicit return contracts rather than executed.
- The real read-only DST `constants.lua`, `tuning.lua` and `strings.lua` layers
  are loaded before the target MOD.
- `GetModConfigData` uses defaults declared by `modinfo.lua` and records their
  provenance in `mod_config.json`.
- `general_mod_debug` supplies traceable world/entity/input/frontend/RPC,
  persistence, scheduler and strict-environment fixtures.
- Unsupported native calls stop the run instead of silently returning a fake
  value.
- Host filesystem I/O, process execution, and network-like RPC delivery are not
  performed.

## Prioritized gaps for broad MOD compatibility

The counts below are a one-time, read-only scan of two representative local MOD
trees. They are included only to prioritize generic APIs; the fixtures do not
copy or identify either MOD.

### Implemented P0 management and entry boundaries

- Capture-only `Prefab`, `Asset`, modern/legacy Recipe, Action, component
  action, Stategraph, user-command, atlas and replicable-component APIs.
- Offline RPC identity and send capture for server/client/shard namespaces.
- Traceable `CreateEntity`, `SpawnPrefab`, Transform/AnimState/Network, tag,
  event, world, input and frontend shapes.
- Isolated persistence, deterministic scheduling, strict MOD_ENV and scoped
  read-only MOD/dependency file access.
- Real DST constants/tuning/strings plus immutable modinfo configuration
  defaults.
- Explicit frontend and dedicated server roles with different `TheNet`, world,
  player and hosted/dedicated flags.
- Opt-in controlled replay for exact Prefab/component post-init, Prefab
  constructor, MOD RPC and Stategraph callbacks.

### Remaining P0: controlled execution boundaries

1. **Prefab loading.** Constructors and registrations are covered, but the
   profile does not automatically follow `PrefabFiles` and execute every
   `scripts/prefabs/*.lua`; this must be an explicit opt-in because prefab
   constructors can greatly expand native requirements.
2. **Wider Hook replay.** Prefab/component post-init is covered by explicit
   plans; player, class, sim and world lifecycle hooks still need finite
   scenario fixtures before they can be replayed safely.
3. **Component/replica depth.** The baseline supplies containers and basic
   objects, not the behavior of every gameplay component or classified netvar.

### P1: common environment and lifecycle fidelity

1. Add cave/forest shard and listen-server variations beyond the current
   frontend, hosted modload and dedicated server roles.
2. Extend deterministic event dispatch (`ListenForEvent`, `PushEvent`,
   `RemoveEventCallback`) and component/replica fixture injection before hook
   replay.
3. Validate dependency ambiguity and target-over-dependency precedence with a
   collision fixture; never search undeclared host directories.

### P2: wider but less universal surfaces

- Frontend widget construction, screen lifecycle, controls, input handlers,
  atlases, minimap registration, and localization registration.
- Stategraph state/event/action objects and buffered-action fixtures.
- Networking/classified/replica synchronization models, still offline and
  explicitly labeled as simulation.
- Asset/build/bank validation against declared archives without rendering.
- Save/load component lifecycle, world migration, shard RPC replay, and
  rollback/reset scenarios.

## Promotion rule

A native shim is promoted from missing to supported only when a fixture proves
its inputs, return value, callback ordering, side effects, failure mode, and
report evidence. Capture-only APIs must stay labeled `CAPTURED`; synthetic
callbacks and time advancement must stay labeled `FIXTURE`/virtual. This avoids
turning broad compatibility into false-positive "successful" runs.
