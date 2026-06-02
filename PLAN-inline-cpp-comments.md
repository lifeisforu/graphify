> **STATUS 2026-06-02 — IMPLEMENTED & VALIDATED (option A, Precise + full node coverage).**
> Engine changes in `graphify/extract.py`: `.h`→`extract_cpp` dispatch; `_strip_ue_macros()`
> blanks UE reflection macros (UCLASS/UFUNCTION/UPROPERTY/GENERATED_BODY/UENUM…) pre-parse
> (position-preserving) — **the real UE blocker**: without it `GENERATED_BODY()` parses as a member
> function whose init-list swallows the next declaration into an ERROR (method node lost); enum +
> enumerator nodes (`EnumName::Value`); method-prototype nodes (`method` edge, `.name()` label);
> `_extract_cpp_rationale()` (leading / trailing-inline / marker→file, attaches by LINE map so it's
> id-scheme-agnostic, drops file-top license headers); UE-macro type-ref filter. Member-var nodes
> already existed (this plan's old assumption was stale). Tests: 11 C/C++ cases in
> `tests/test_rationale.py`, full suite 457 passed / 0 regressions.
> Deployed editable into PN env (`uv pip install -e`, rebuild with `UV_NO_SYNC=1`), wiped `cache/ast`,
> `rebuild-all` (26/26 modules, graph.json 60→109 MB): 16,186 rationale nodes / 16,995 `rationale_for`
> edges (methods 6752, enum-values 723, class/var 6999, file markers 2521). `explain` shows the
> rationale connection; TODO/HACK debt-map seeds onto rationale nodes.
> **Remaining:** user submits regenerated graph.json (`p4 reconcile -n` → 1765 edits + graph.json);
> publish engine to PyPI + version-bump so teammates' rebuilds match; NL seeder still prefers
> identifiers over comment prose for free-text queries (engine query-layer follow-up, not extraction).

# Plan — Inline C/C++ comment (rationale) extraction in graphify

> Saved 2026-06-02 for a future session. Goal: pull code comments (Doxygen `///`,
> `/** */`, and `// NOTE:`/`// TODO:` markers) into the knowledge graph as
> `rationale` nodes linked to code nodes — for C/C++ (UE5/PN). Today only Python does this.
> This is option **(A)** from the discussion. Option **(B)** (cross-tag restitch) is already
> DONE — see "Related" at the bottom.

## Why it's worth doing (advantages)

- **NL queries match intent, not just identifiers.** Seed matching is currently over node
  labels (= symbol/file names) only, which is why `"coi provider 와 mutable"` once seeded onto
  `COIBulkUpdateTestCommandlet`. Comment text as nodes lets concept queries
  (`"inflight 제약 우회"`, `"stale 콜백 차단"`) land on the right node.
- **A "why" layer AST can't express** — rationale, contracts, failure modes live only in comments.
- **Answers complete without file reads**, and work even when source isn't synced (graph.json only).
- **Readable node dumps** (each node gets a one-line summary) + **TODO/HACK debt map**.
- **Synergy with (B):** islands now connect, so cross-module traversals reach engine nodes; if those
  carry doc-comments, the meaning comes along. (B) = reach, (A) = meaning at the destination.

## Current state (verified 2026-06-02)

- Engine dev source: **`F:\GitHub\graphify`** (PyPI pkg `lifeisforu-graphify`). The PN venv at
  `F:\p4\PN_Claude\Claude\Graphify\env\.venv` installs it via `uv sync --upgrade` (latest from PyPI).
- **Only Python extracts comments:** `_extract_python_rationale` (`graphify/extract.py:3483`).
  It creates nodes `{file_type:"rationale", label: comment text, source_file, source_location}` and
  edges `{relation:"rationale_for", confidence:"EXTRACTED"}`. Prefix list `_RATIONALE_PREFIXES` (`:3459`).
  `serve.py` renders these generically (shows `file_type` + `relation`); they're excluded from
  callable cross-file resolution but DO appear in `query`/`explain` output.
- **C/C++ has NO comment pass:** `extract_c` (`:4000`) and `extract_cpp` (`:4005`) call only
  `_extract_generic`.

## Blockers — UE-specific, must solve (NOT just copy the Python pass)

1. **`.h` → `extract_c`** (dispatch ~`:10043`), and `_C_CONFIG` (`:1888`) has
   `class_types=frozenset()` (empty) + `function_types={"function_definition"}` only. So headers
   parsed as C produce **no class/struct nodes and no prototype nodes**. UE's `///` docs live mostly
   on **header declarations** → there is nothing to attach them to.
   - Fix: route `.h` to `_CPP_CONFIG` (or a UE-aware config) so classes/structs are captured, AND
     emit nodes for declarations/prototypes.
2. **Prototypes are explicitly skipped** (~`:2770`, "Skip method prototypes…"). Header method
   declarations need nodes to carry their doc-comments.

## Scope options (pick one)

- **Precise** — route `.h`→C++ config + emit declaration/prototype nodes + attach `///` / `/** */`
  per method / class / struct / enum. Best precision; larger engine change.
- **Lightweight** — no new node kinds: attach header doc-comments to the enclosing class/struct node
  (or the file node), and attach `.cpp`-definition comments at function level. Minimal change, fast,
  but coarser (no per-prototype docs in headers).

## Implementation steps

1. Add `_CPP_RATIONALE_PREFIXES = ("// NOTE:","// IMPORTANT:","// HACK:","// WHY:","// TODO:","// FIXME:","//!")`.
2. Write `_extract_cpp_rationale(path, result)` (shared for C & C++), mirroring the Python one:
   - Parse with `tree_sitter_cpp`.
   - Walk tree; for each declaration (`function_definition`, `class_specifier`, `struct_specifier`,
     `enum_specifier`, prototype/`field_declaration`, and—precise option—`declaration`), find the
     immediately-preceding sibling `comment` node(s); gather contiguous `///`/`//!` lines or a
     `/** */` / `/*! */` block; strip the markers.
   - Compute the target node id the SAME way `_extract_generic` does: functions via
     `_make_id(stem, func_name)` using `_get_cpp_func_name`; classes/structs via
     `_make_id(stem, class_name)`. (`stem` from `_file_stem` `:79`; `_make_id` `:63`.)
   - Add a rationale node + `rationale_for` edge (mirror Python `_add_rationale`).
   - Also scan lines for `_CPP_RATIONALE_PREFIXES` → attach to the file node.
   - Noise control: cap label ~80 chars (like Python), require a min length, dedup by
     `(stem,"rationale",line)`.
3. Wire into BOTH `extract_cpp` AND `extract_c`:
   ```python
   def extract_cpp(path):
       result = _extract_generic(path, _CPP_CONFIG)
       if "error" not in result:
           _extract_cpp_rationale(path, result)
       return result
   # same for extract_c  (+ Blocker 1: make .h capture classes / route .h to _CPP_CONFIG)
   ```

## CRITICAL operational gotcha — cache invalidation

The AST cache key is **SHA256 of file content ONLY** (`graphify/cache.py:133-136`), NOT the extractor
version. After editing `extract.py`, unchanged files reload **stale cached AST without comments** →
the change silently no-ops. You MUST:
- wipe `F:\p4\PN_Claude\Claude\Graphify\graphify-out\cache\ast\`
- run a full rebuild: `bash .../pn-graphify/scripts/rebuild-all.sh --graphout "<graphout>"` (it `--prune`s)

## Delivery / test path

- The engine change is in `F:\GitHub\graphify` (NOT Perforce). The PN env installs from PyPI.
- To test a LOCAL engine change without publishing: point the env at local source
  (editable: `uv pip install -e F:\GitHub\graphify` inside `Graphify/env`, or add as a path dep),
  OR bump version + publish to PyPI then run `Plugins\setup.bat`.
- Then: wipe `cache/ast` → `rebuild-all` → verify (see queries below).
- `p4 reconcile -n` on graphout → **stop. NEVER auto-submit** (user submits the regenerated
  `graph.json` + any plugin changes).

## Validation queries (after rebuild)

- `query.sh "inflight 제약 우회"` → should land on `EPN_COIProviderPriority::Immediate`.
- `query.sh explain "<some function>"` → connections should include `rationale_for` nodes.
- `query.sh "TODO"` / `"HACK"` → tech-debt map.

## Key file refs (`F:\GitHub\graphify\graphify\`, line numbers ~ may drift — re-grep)

- `extract.py`: `_extract_python_rationale` 3483, `_RATIONALE_PREFIXES` 3459, `_C_CONFIG` 1888,
  `_CPP_CONFIG` 1902, `extract_c` 4000, `extract_cpp` 4005, dispatch table 10038+,
  prototype skip ~2770, `_make_id` 63, `_file_stem` 79.
- `cache.py`: cache key 133-136, `load_cached` 158.
- `serve.py`: generic node/edge render (uses `file_type`, `relation`).

## Related — (B) cross-tag restitch is DONE

`merge_graphs.py` (PN plugin) now has `restitch_cross_repo()`: after `compose_all`, it indexes
definition file nodes by basename and adds `resolves_to` edges from label-less reference stubs to the
matching header (.h preferred) in every repo (skip basenames shared by >4 repos). Result: cross-repo
edges 0 → 731, 32 module pairs connected, COI↔Mutable path now resolves. Shipped in **CL 412**
(`merge_graphs.py` + regenerated `graph.json` + `.graphify_roots.json`) — **submitted 2026-06-02**
(live in depot; teammates get it on `p4 sync`). No plugin version bump needed (internal script runs
from depot in-place).
