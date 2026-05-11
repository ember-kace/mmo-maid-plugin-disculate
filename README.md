# Disculate

An in-Discord calculator plugin for [MMO Maid](https://mmomaid.com). Arithmetic, percentages, common math functions, and constants — without leaving the channel.

```
/calc expression: (3 + 4) * sqrt(16)
                                              ┌────────────────────────────┐
                                              │ `(3 + 4) * sqrt(16)` = **28** │
                                              └────────────────────────────┘
```

Built for the MMO Maid platform's sandboxed plugin runtime. Safe-tier capabilities only (`interaction:respond`, `storage:kv`). No outbound HTTP, no disk writes, no `eval`/`exec`/`compile` on user input.

## Slash commands

| Command | Who | Purpose |
|---|---|---|
| `/calc expression:<text> [ephemeral:<bool>]` | Anyone | Evaluate a math expression. `ephemeral:true` hides the result from the channel. |
| `/calc-config [precision:<int>] [angle_mode:<rad\|deg>] [scientific_threshold:<int>]` | Server admin (`MANAGE_GUILD`) | Set per-server defaults. Omitted options keep their current value. |
| `/calc-help` | Anyone | Quick reference for syntax, functions, and constants. |

## Supported syntax

**Operators**: `+`  `-`  `*`  `/`  `//`  `**`  unary `+`/`-`  parentheses

**Percent**: trailing `%` divides by 100 (e.g. `50%` → `0.5`, `200 * 5%` → `10`)

**Constants** (case-sensitive): `pi`  `e`  `tau`

**Functions**:

| Category | Names |
|---|---|
| Basic | `abs(x)` `round(x[, n])` `floor(x)` `ceil(x)` `min(a, b, ...)` `max(a, b, ...)` `mod(a, b)` `pow(a, b)` |
| Roots / exp / log | `sqrt(x)` `exp(x)` `log(x[, base])` `log10(x)` `log2(x)` `ln(x)` |
| Trig (honours `angle_mode`) | `sin` `cos` `tan` `asin` `acos` `atan` `atan2(y, x)` |
| Hyperbolic | `sinh(x)` `cosh(x)` `tanh(x)` |

## Examples

| Input | Output |
|---|---|
| `2 + 2` | `4` |
| `1/3` | `0.333333` (precision-dependent) |
| `200 * 5%` | `10` |
| `100 + 10%` | `100.1` (10% = `0.1`, **not** "10% of 100"; see [ARCHITECTURE.md §B](ARCHITECTURE.md)) |
| `sqrt(2)` | `1.414214` |
| `sin(30)` with `angle_mode:deg` | `0.5` |
| `mod(-7, 3)` | `2` (sign-of-divisor) |
| `1e308 * 10` | error: *Result is too large to represent.* |
| `2^3` | error: *Use `**` for power, not `^`.* |
| `5 % 3` | error: *Use `mod(a, b)` for modulo. Trailing `%` means percent.* |

If you make a common calculator-keyboard mistake (`^` for power, `2(3)` for implicit multiplication, `==` for comparison, etc.), Disculate emits a specific hint pointing at the supported equivalent instead of a generic "syntax not allowed."

## Configuration

`/calc-config` adjusts three per-server settings, persisted in plugin KV:

| Setting | Range | Default |
|---|---|---|
| `precision` | `0`–`10` decimal places | `6` |
| `angle_mode` | `rad` / `deg` | `rad` |
| `scientific_threshold` | `1`–`20` (switch to scientific notation when `\|result\| ≥ 10^N`) | `12` |

A per-user cooldown of 2 seconds prevents accidental spam. Errors are always shown ephemerally to the invoker only.

## Safety model

- **No `eval` / `exec` / `compile` on user input.** The parser uses stdlib `ast.parse(mode="eval")` and a manual node-allowlist walker. The audit gate (`tools/run_audit.py`) scans for these calls and blocks any from being committed.
- **Defense-in-depth DoS guards**: 120-char input cap, 32-deep AST cap, 200-node AST cap, `**` operand guard that routes large operands through `math.pow` (so bignums can't OOM the sandbox), and a 200 ms wall-clock budget.
- **Mention injection defeated** at two layers: `safe_text` inserts zero-width spaces between `@` and `everyone`/`here`, and every response sets `allowed_mentions: {"parse": []}`.
- **NFKC normalisation** + bidi/control-char rejection on every input before parsing.

See [AUDIT-REPORT.md](AUDIT-REPORT.md) for the full audit trail.

## Local development

```powershell
# Requirements: Python 3.11+ (tested on 3.11–3.14)

# Run the test suite (195 tests, ~0.1s)
py -m pytest tests/ -q

# Build the deterministic production bundle (build/disculate.zip)
py tools/build_bundle.py

# Run all 7 audit gates (manifest, imports, no_eval, todo_markers, plugin_run, pytest, bundle)
py tools/run_audit.py
```

The bundle excludes everything outside an explicit allowlist (see `tools/build_bundle.py:INCLUDED_FILES`). Tests, tools, documentation, and dotfiles never ship.

## Project layout

```
disculate/
├── manifest.json            ← plugin id, capabilities, slash commands
├── plugin.py                ← handler entry points (must end with plugin.run())
├── lib/
│   ├── parser.py            ← cleaning, percent preprocessing, ast.parse + allowlist walker
│   ├── evaluator.py         ← AST walk, DoS guards, wall-clock budget
│   ├── functions.py         ← FunctionSpec registry (one entry per math function)
│   ├── format.py            ← result formatting (precision, scientific, int preservation)
│   ├── config.py            ← per-server KV config + schema versioning
│   ├── embed.py             ← response builders + safe_text/clip/help generation
│   ├── reasons.py           ← reason codes + user-facing hints
│   └── logctx.py            ← request_id ContextVar for log correlation
├── tests/                   ← 195 tests: smoke, unit, handler, failure-injection, adversarial
├── tools/
│   ├── build_bundle.py      ← deterministic zip with allowlist guard
│   └── run_audit.py         ← 7 audit gates
└── docs (CLAUDE.md, AUDIT-REPORT.md, ARCHITECTURE.md, RUNBOOK.md, SDK-ASSUMPTIONS.md)
```

## Documentation

| Document | Audience |
|---|---|
| [README.md](README.md) | Users + first-time contributors. You are here. |
| [CLAUDE.md](CLAUDE.md) | The next maintainer (or LLM). TL;DR, recipes, things-that-look-wrong-but-aren't. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Why each design decision beat its alternatives. |
| [AUDIT-REPORT.md](AUDIT-REPORT.md) | Full audit trail across R1, R2, R3, and the math-shape Tailored round. |
| [SDK-ASSUMPTIONS.md](SDK-ASSUMPTIONS.md) | Every defensive try/except that exists because the SDK doc was incomplete — the post-deploy probe list. |
| [RUNBOOK.md](RUNBOOK.md) | Operational scenarios: OOM, KV quota, schema migration, rollback. |
| [CHANGELOG.md](CHANGELOG.md) | Per-version Added / Changed / Fixed. |

## Contributing

The single-paragraph recipe for "add a math function" is in [CLAUDE.md → Common task recipes](CLAUDE.md#common-task-recipes). The audit gates in `tools/run_audit.py` are the merge bar: if `py tools/run_audit.py` exits non-zero, the change isn't shippable.

Before opening a PR:

```powershell
py -m pytest tests/ -q   # all green
py tools/run_audit.py    # all 7 gates pass
```

## License

No license file ships with the repository. By default, this means the work is **all rights reserved** to its author — read, but don't redistribute or build derivatives without permission. A formal license may be added later.
