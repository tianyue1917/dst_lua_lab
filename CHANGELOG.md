# Changelog

## 0.1.1

### Fixed

- Force text fixtures to LF on every checkout so the Windows and Linux CI matrix exercises identical Lua input bytes.
- Update GitHub Actions to their Node.js 24-based major versions.

## 0.1.0

Initial public release.

### Added

- Isolated algorithm and MOD-loading Workers for Lua 5.1 and LuaJIT runtimes.
- `doctor`, local `scripts.zip` configuration, and Module/Case scaffold commands.
- `modload`, `frontend`, and `server-sim` role fixtures.
- Capability Module and Case Pack Extension API v1.
- Explicit, single-use controlled replay for selected Hook, Prefab, RPC, and Stategraph callbacks.
- Read-only VFS, structured reports, deterministic scheduling, in-memory persistence, and strict Missing Native diagnostics.
- Source, sdist, and Wheel workflows with bundled built-in extensions.
- Windows and Linux CI plus repository-sensitive-content scanning.

### Security boundaries

- Disabled Lupa Python bridges, Lua debug access, LuaJIT FFI loaders, host process execution, and unrestricted file I/O for target Lua.
- Isolated Worker import paths and generated output roots.
- Added Manifest and entry-point Hash verification before trusted extension execution.
- Rejected symlink and Windows reparse-point state/output paths.
