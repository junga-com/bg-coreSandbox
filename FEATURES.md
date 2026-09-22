# bg-coreSandbox — Feature Summary

This sandbox holds three related projects that together form a system for writing, documenting,
testing, packaging and administering bash-based Linux tooling.

| Project | Role | Installed on |
|---|---|---|
| **bg-core** | Runtime bash library + host administration commands. Sourced by scripts via `/usr/lib/bg_core.sh`. | Target hosts (runtime dependency) |
| **bg-dev** | Development-time toolchain: project/asset model, packaging, docs, tests, debugger UIs, VMs. | Developer machines only |
| **bg-core-bash-builtins** | C loadable bash builtins (`bgCore`, `import`) that accelerate the hot paths of bg-core. | Optional; transparent speedup |

The guiding idea is that **the OS is the platform**. Scripts, libraries, plugins, config files,
man pages, cron entries and daemons are all first-class *assets* that live in a project folder,
get scanned into a manifest, and get installed onto a host by a `.deb`/`.rpm` package — or
*virtually* installed into a single terminal for development.

---

## 1. bg-core — the runtime library

A script opts in with one line:

```bash
source /usr/lib/bg_core.sh
```

That sets up the host security environment and unconditionally imports everything under
`core/`. Additional libraries are pulled in with the `import` statement; some `coreOnDemand/`
libraries load themselves automatically the first time you use an entry-point function.

### 1.1 Module / import system

`import <lib.sh> ;$L1;$L2` is a wrapper over `source` that is **idempotent** (safe to call
repeatedly, so libraries can declare their own dependencies), searches a **secure system path**
(callers never hardcode paths), cooperates with virtually-installed project folders, and lets the
dev environment re-source only the libraries that changed mid-run. The trailing `;$L1;$L2` is
required syntax — it is what causes the library to be sourced in the *global* context rather than
inside a function scope.

Related: `importCntr`, `findInPaths`, `bgGetDataFolder`, `bgListInstalledProjects`.

### 1.2 Error handling and exceptions

An `assert*` family gives bash something close to throw/catch:

- `assertError`, `assertLogicError`, `assertNotEmpty`, `assertFileExists`, `assertPathExists`,
  `assertValidFilename`, `assertNoBashSpecialChars`, … plus `Throw` / `Rethrow`.
- `Try: … Catch: && { … }` blocks, with `catch_errorClass`, `catch_errorCode`,
  `catch_errorDescription`, `catch_stkArray`, `catch_psTree` available inside the handler.
  `TryInSubshell` covers the subshell case.
- Uncaught asserts print the *failing source line plus the values of the variables used on that
  line* — a useful diagnostic for an end user. With tracing on, a full annotated BASH call stack
  and process tree are printed instead.
- `$assertOut` is the conventional temp file for capturing a command's stderr so `assertError` can
  fold it into the report: `cmd 2>$assertOut || assertError`.

Stack machinery lives in `bg_coreStack.sh`: `bgStackFreeze`, `bgStackPrint`, `bgStackDump`,
`bgStackToJSON`, `bgStackFrameFind`, `bgGetPSTree`.

### 1.3 Tracing and debugging

`bg_debugTrace.sh` provides a tracing channel that is a no-op until a destination is set
(`bg-debugCntr trace on:`), so trace calls can be left in production code:

`bgtrace`, `bgtracef`, `bgtraceLine`, `bgtraceVars`, `bgtraceParams`, `bgtraceStack`,
`bgtracePSTree`, `bgtraceXTrace on|off`, `bgtraceRun`, `bgtraceBreak` (drop into the debugger),
`bgtimerStartTrace`/`bgtimerLapTrace`, `bglog`.

The debugger *engine* is in bg-core (`debuggerOn`, `debugBreakAtFunction`,
`debuggerAttachToGdb`); the debugger *front ends* ship in bg-dev.

### 1.4 Variable, string and array toolkit

- `bg_coreBashVars.sh` — introspection (`varExists`, `varGetAttributes`, `varIsAMapArray`,
  `varGetNameRefTarget`), heap variables (`newHeapVar`), marshalling (`varMarshal`,
  `varUnMarshalToGlobal`, `arrayToJSON`, `varContextToJSON`), safe escaping to/from bash tokens,
  and container ops for arrays (`arrayPush/Pop/Shift/Unshift/Find/Delete/Size`), sets
  (`setAdd/setHas/setDelete/setSize`) and maps (`mapSet/mapGet/mapGetKeys/mapDelete`).
- `bg_coreStrings.sh` — splitting and tokenizing (`stringSplit`, `stringSplitIntoBashTokens`,
  `parseOneBashToken`), URL parsing, escaping for eval/regex, trimming/filling/shortening,
  `numToHuman`, `dedent`, a full **string-set algebra** (`strSetAdd/Subtract/Union/Intersection/
  Sort/Filter/ExpandRangeNotation`), path helpers (`pathGetCommon`, `pathGetCanonStr`,
  `pathCompare`), and deb-control-file parsing.
- `bg_corePrintfVars.sh` — **`printfVars`**, a single function that pretty-prints scalars, arrays,
  associative arrays and object instances (recursively) in a compact aligned form. Its output is
  copy-pasteable back into a terminal to recreate the state. `printfTable` formats tabular data.

### 1.5 Command-line structure (the "out-of-band" system)

`bg_outOfBandScriptFeatures.sh` + `oob_invokeOutOfBandSystem "$@"` give every script, for free:

- **Bash completion** driven from inside the script itself (`bgBCParse`, `bgCmdlineParse`,
  `bgMakeUsageSpec`), including `<placeholder>` hints that describe what the next argument is.
  Options are gleaned automatically from the standard options loop.
- **Help** — `-h` opens the script's man page; override with `oob_helpMode()`.
- **Privilege enforcement** — define `oob_getRequiredUserAndGroup()` and the script re-invokes
  itself under `sudo -u<user>` as needed.
- **Daemon control verbs** when `daemonDeclare` was called.
- A reminder banner when tracing is enabled, and umask normalization.

Argument parsing itself is the `bgOptionGetOpt` / `bgOptionsEndLoop` idiom, which supports the
complete *nix option convention (`-v`, `--verbose`, `-u<val>`, `-u <val>`, `--user=<val>`,
`--user <val>`, bundled short flags) in one line per option.

### 1.6 Return-value conventions

Because forking a subshell for `$(...)` is expensive, library functions return values by
reference: `returnValue`, `outputValue`, `varOutput`, `setReturnValue`, and the
`bgOptions_DoOutputVarOpts` helper that gives a caller the choice of
`-R <scalar>` / `-A <array>` / `-S <set>` / stdout — all from one implementation.

### 1.7 Configuration files

- `bg_ini.sh` (the largest single library) — read/write INI *and* non-INI config formats while
  **preserving existing order, comments and human formatting**: `iniParamGet/Set/Remove/List`,
  `iniSectionGet/Replace/Remove/List`, `configLineReplace`, `configDropinCntr`, `iniValidate`,
  plus matching `cr_*` declarative-config classes.
- `bg_config.sh` — a *scoped*, virtual config file for the host/domain: `configGet`, `configSet`,
  `configGetAll`, `configScopeList`, `configFlatten`. A domain admin sets a default for many hosts;
  a local admin overrides it; the most specific value wins.
- `bg_template.sh` — template expansion against live shell/environment variables
  (`%VAR%`, `%var:default%`): `templateExpandStr`, `templateExpand`, `templateExpandFolder`,
  `templateFind`, `templateList`, `templateTree`, `templateListVars`. *System templates* are
  referenced by bare filename and can only come from privileged locations, so template content
  used to configure daemons is trustworthy.

### 1.8 Filesystem, process and time

- `bg_coreFiles.sh` — `bgmktemp`/`fsMakeTemp --auto` (auto-cleaned temp files), `fsIsNewer`,
  `fsIsDifferent`, `fsGetAge`, `fsMakeSymLink`, `fsMergeFoldersRecursively`, `fsCopyAttributes`,
  `bgtee`, `fsPipeToFile`. `bgfind`/`fsExpandFiles` in `bg_coreLibsMisc.sh`.
- `bg_bgsed.sh` / `bg_bgawk.sh` — `bgsed` and `bgawk` wrappers that behave sanely on missing or
  empty files, do in-place edits safely, and escalate privilege only when needed.
- `bg_coreProcCntrl.sh` — `bgsleep`, `bgwait`/`bgwaitAll`, `procIsRunning`, `delayedExec`,
  `runPluginCmd`, and a **cron expression engine** (`cronNormSchedule`, `cronShouldRun`,
  `cronGetNextTime`).
- `bg_coreTimer.sh` — nanosecond timers and human time-period conversion.
- `bg_coreSemVer.sh` — `versionCompare`, `versionLt/Gt/Eq`, `versionIncrement`.
- `bg_coreLSBVersions.sh` — distro/codename/version detection and `lsbVersionAtLeast`.
- Robust signal/trap management: `bgtrap`, `BGTRAPEntry/Exit`, `bgTrapStack`, `bgkillTree`,
  `bgExit`, plus `startLock`/`endLock`.

### 1.9 Terminal UI

- `bg_cui.sh` — CSI/ANSI primitives: cursor and scroll-region control, screen dimensions,
  color tables, `printfAt` with buffered output and viewports, `wrapLines`, CSI-aware string
  functions (`csiStrlen`, `csiSubstr`, `csiStrip`), `cuiReadKey`, `promptForPassword`, `bgbind`.
- `bg_cuiWin.sh` — a script running on a desktop can **open extra terminal windows** as UI panes
  (`cuiWinOpen`, `cuiWinCntr`, `cuiWinExec`). Used by the debugger and progress UIs.
- `bg_cuiProgress.sh` + pluggable renderers (`bg_progressOneline.sh`,
  `bg_progressStatusline.sh`, `bg_progressTermTitle.sh`, array/tmpfile contexts) — a script just
  calls `progress`; *the environment and user preference* decide whether that becomes a status
  line, a terminal title, a separate window, or nothing.
- `bg_coreCuiUserApps.sh` — find the user's preferred editor/pager/browser/diff tool/file manager,
  detect SSH vs GUI (`wheresTheUserAt`, `isGUIViable`), `confirm`, `notifyUser`.

### 1.10 Object-oriented bash

`bg_objects.sh` adds real nestable data structures to bash — its primary purpose — with an OO
syntax as the ergonomic layer:

```bash
DeclareClass MyData
function MyData::__construct() { this[filename]="$1"; $this.data=new Array; }
ConstructObject MyData d1 /tmp/data
$d1.read
printfVars d1
```

Features: single inheritance (`DeclareClass <name> <baseClass>`), virtual method tables,
static methods (`static::Class::…`), dynamic construction, `Object::clone/get/set/getMethods/
hasMethod/addMethod/getSize`, built-in `Array`, `Map` and `Stack` classes, and serialization to
and from **JSON, INI, flat-INI, deb-control, strings and files** (`Object::toJSON`,
`Object::fromJSON`, `Object::saveFile`, `Object::restoreFile`, `ConstructObjectFromJson`).
`bg_mysql.sh` adds `Object::toSQL`/`fromSQL`.

With the `bgCore` C builtin loaded, object method dispatch is in the same performance class as a
native bash function call.

### 1.11 JSON

`bg_json.sh` (`jsonRead`, `jsonAwk`, `jsonEscape`/`jsonUnescape`, object (de)serialization) with
an awk implementation for streaming and a C implementation in the builtin for speed.

### 1.12 Plugins

`bg_plugins.sh` formalizes cross-package extension. A package publishes a **plugin type** as
`<Name>.PluginType`; any other package then ships `<instance>.<Name>` files that are discovered
automatically once installed. Plugin instances are objects (`DeclarePlugin`,
`DeclarePluginType`, `Plugin::invoke`, `static::Plugin::list/get/types/loadAllOfType`).
Plugins may be written in any language as long as they follow the protocol.

bg-core defines four plugin types and ships instances of each:

| Plugin type | Purpose | Control command |
|---|---|---|
| `Collect` | Periodically snapshot host state into a shared domain folder | `bg-collectCntr` |
| `Standards` | Check host compliance against a baseline and report | `bg-standardsCntr` |
| `Config` | A discrete unit of configuration that can be checked *or applied* | `bg-configCntr` |
| `RBACPermission` | Declare a named sudo capability granted via group membership | `bg-rbacPermissionCntr` |

### 1.13 Declarative configuration (creqs)

"creq" = *configuration required*. A creq class is like a command with a `check` operation and an
`apply` operation; the runner only applies when the check fails, giving idempotency for free.

```bash
DeclareCreqClass cr_myConfFile
function cr_myConfFile::check() { [ -e /tmp/myConfig.conf ]; }
function cr_myConfFile::apply() { echo "hello world" > /tmp/myConfig.conf; }
creqApply cr_myConfFile
```

`bg_creqs.sh` supplies the runners (`creq`, `creqCheck`, `creqApply`, sessions, change tracking,
policy IDs, state DB flushing) and `bg-creqApply` / `bg-creqCheck` run a single statement from the
shell. `bg_creqsLibrary.sh` ships ~70 ready-made classes: users, groups, sudo config, symlinks,
files and file content, folders, packages, daemons, ports, ssh hardening, timezone, rsyslog, git
folders, mysql objects, and more. Grouping creq statements into a `Standards` or `Config` plugin
turns them into a distributable compliance/configuration unit.

### 1.14 Access control

- `bgsudo` — a `sudo` wrapper that works out the *minimum* privilege actually required for a
  command and escalates only that far. The invoking user still needs the rights.
- `oob_getRequiredUserAndGroup()` — the opposite model: authorizes *the script* to do things the
  user cannot do directly, so an LDAP-driven group membership can grant a narrow capability.
- `RBACPermission` plugins generate the sudoers config, including per-host and per-tag group
  variants (`<perm>-<hostGroup>`) driven by `/etc/tags`.

### 1.15 awkData — the state database

`bg_awkData*.sh` + `bg-awkData` provide a low-ceremony text database used as a uniform query layer
over the host's disparate native config files and commands. Builder plugins translate native data
into cached tables; the native files stay the system of record.
`awkData_query`, `awkData_getValue`, `awkData_countValues`, `awkData_tableInfo`, schema files
(`*.awkDataSchema`) and full command-line completion of table/column/value terms.

### 1.16 Daemons

`daemonDeclare "$@"` before `oob_invokeOutOfBandSystem "$@"` turns a script into a well-behaved
daemon: `start|stop|restart|status|reload`, `-F` foreground mode, PID and log file management with
correct ownership when dropping privilege, and auto-start registration against **systemd, upstart
or SysV** depending on the host. `daemonCheckForSignal INT TERM` lets the main loop handle signals
*synchronously* for graceful shutdown. `bg_coreDaemon.sh` also exposes the full control API
(`daemonCntrStart/Stop/Enable/InstallAutoStart/TailLog/…`).

### 1.17 Other

- `bg_manifest.sh` — the host asset manifest: which package provides which asset
  (`manifestGet`, `manifestGetPkgForPath`, `manifestSummary`).
- `bg_ipc.sh` — message pipes, plus SSH connection caching/multiplexing helpers (`sshCmd`,
  `sshConfigLocalConnectionCaching`, sshfs setup).
- `bg_mysql.sh` — install/bootstrap MySQL, SSO root login, create DBs/users/grants, timezone data,
  plus `cr_mysql*` creq classes.
- `bg_qemu.sh` + `bg-qemu` — mount/unmount and modify QEMU disk images; the basis for bg-dev's
  FreshVMs.
- `bg_onPkgInstRm.sh` — `preinst`/`postinst`/`prerm`/`postrm` hooks for packages built by bg-dev.
- `bg_unitTest.sh` + `bg-utRunner` — the unit test runtime (see bg-dev, §2.5).

### 1.18 bg-core commands

`bg-core` (templates / cuiWin / plugins / config subcommands), `bg-awkData`, `bg-collectCntr`,
`bg-configCntr`, `bg-standardsCntr`, `bg-rbacPermissionCntr`, `bg-creqApply`, `bg-creqCheck`,
`bg-complianceEngineDeamon`, `bg-qemu`, `bg-utRunner`.

---

## 2. bg-dev — the development toolchain

### 2.1 Project types

Project types are bash objects in a hierarchy, so operations are polymorphic — `publish` does the
right thing for the kind of project it is run in.

- **`Project`** — base: a git-controlled folder with a `.bg-sp/config`.
- **`SandboxProject`** — a folder collecting several related projects (this repo). SDLC
  operations fan out across every sub-project, doing the right thing per project based on whether
  it changed.
- **`PackageProject`** — builds into a `.deb` or `.rpm`.
- **`NodejsProject`**, **`AtomPluginProject`**, **`BashBuiltinProject`** — specializations.

### 2.2 Assets

A package project is a bag of *assets*, discovered by path/extension/content and recorded in a
manifest. Asset types are **hierarchical** (`lib` → `lib.script` → `lib.script.awk`), so install
logic can be generic or specific. Built-in types include: `Cmd`, `lib.bash`, `AwkLib`, `Data`,
`Doc`, `Etc`, `Opt`, `Cron`, `Manpage`, `SysDInit`, `SysVInit`, `Syslog`,
`GlobalBashCompletion`, `UnitTest`, plus plugin-provided types (`awkDataSchema`, `builtin`,
`python`, `template`). New asset types are added as `*.PackageAsset` plugins from any package.

Operations: `find` (list), `addNew`, `install`.

### 2.3 In-place ("virtual") development

`source bg-debugCntr` then `bg-debugCntr vinstall <project|sandbox>` rewrites the *terminal's*
environment — PATH, library import paths, man paths, `BASH_LOADABLES_PATH`, plugin and template
search paths — so project source folders shadow anything installed on the host. You edit a file
and the feature is live, with no build or install step.

Guard rail: this requires `/etc/bgHostProductionMode` to contain `mode=development`, which needs
privilege to create. Development-time features cannot be used to bypass security on a host you
don't administer.

### 2.4 Debugging

A complete bash debugger written in bash, with three front ends:

- **Integrated** (`bg_debugger_integrated.sh`) — in-terminal, using the terminal's alternate page;
  works over SSH. Code view, stack view, watch/variables window, key maps.
- **cuiWin** (`bg_debuggerCUIWin.sh`) — opens a separate terminal window on a desktop.
- **Atom** (`bg_debugger_atom.sh`) — attaches to the `bg-atom-bash-debugger` editor plugin.

Entry points: prefix a command with `bgdb`, insert `bgtraceBreak`, `bg-debugCntr debugger
stopOnAssert:on`, `bg-debugCntr debugger cntr-C:on`, or `<utFile>.ut debug <testcase>`.
`bg-debugCntr debugger destination <driver>:<dest>` selects the UI.

### 2.5 Unit tests

Test files are `unitTests/<lib>.sh.ut` with `#!/usr/bin/env bg-utRunner` as the shebang, so they
are directly executable *and* get bash completion without being installed.

```bash
declare -A ut_myFunc=( ["test42"]="$(cmdline 42 "something")" )
function ut_myFunc() { ut setup; …; ut test; myFunc "$@"; }
```

The `ut` function marks `setup` vs `test` regions (setup failures mean *not eligible to run*,
not *failed*) and supports output `filter` regexes to redact volatile values. The framework
records stdout, stderr and non-zero exit codes, and echoes each source line next to its output.

Verification is by **golden output**: the recorded run (`.<file>.run`) is compared to committed
expected output (`.<file>.plato`). Lines starting with `#` or `//` are commentary and excluded
from the comparison. This makes error paths as easy to test as success paths, and the git history
of the `.plato` files becomes the history of the project's observable behavior.

`bg-dev tests list|run|report|show|parse`, and testcase IDs look like
`<project>:<utFile>:<utFunction>:<cmdlineName>`.

### 2.6 Funcman — documentation from source

`bg-dev funcman update` scans bash and awk sources and generates man pages: **man(1)** per command
(and per sub-command), **man(7)** per library (with an auto-generated function list), **man(3)**
per public function, plus explicit pages from `# MAN(<section>) <name>` blocks. The conventions
are deliberately loose — an ordinary comment block above a function becomes its page; `# usage:`
lines become the synopsis; `# <Label>:` lines become sections (`Options:`, `Params:`,
`Return Value:`, `See Also:`). Directives (`# FUNCMAN_SKIP`, `# FUNCMAN_AUTOOFF/AUTOON`,
`# FUNCMAN_NO_FUNCTION_LIST`) control generation. Functions starting with `_` are private and get
no page. Funcman also builds the project's ctags file. Output is templated, so other formats
(e.g. linked HTML) can be added.

### 2.7 Packaging and SDLC

- `bg-dev init` / `bg-dev newProj` — create the `.bg-sp/` metadata or a whole new project from a
  template (`bg-dev/data/projectTemplates/`, `bg-dev/templates/newAsset.*`).
- `bg-dev assets scan|list|update|summary|addNewAsset|listAssetTypes`.
- `bg-dev install` / `uninstall` — copy assets into a destination filesystem tree.
- `bg-dev pkg clean|build|localInstall|localUninstall` — build `.deb`/`.rpm`.
- `bg-dev sdlc status|origin|commit|push|pull|publish|bumpVersion|revert` — polymorphic across a
  sandbox's sub-projects.
- `bg-dev status` — per-project 3-character indicator (uncommitted / unpushed / unreleased) plus
  version and change counts.
- `bg-dev foreach`, `bg-dev clone`, `bg-dev sandbox preCommit|status`.
- `bg-dev npm` / `analyze` (`buildDeps`, `buildRaw` bash dependency analysis) / `bashBuiltins`
  (valgrind harness for the C builtins) / `make`.

### 2.8 FreshVMs

`bg-dev tests FreshVMs …` creates throwaway VMs (Kvm or Multipass driver plugins) running various
OS versions and shares the current sandbox into them, so a project can be tested in a clean
environment. This catches undeclared dependencies that happen to already be installed on the
developer's machine. New OS images are registered by dropping a cloud image into
`~/.bg/cache/bg-dev_vmImages/osCloudImages/` and adding a line to its `index.dat`.

---

## 3. bg-core-bash-builtins — native acceleration

A bash *loadable builtin* (`bgCore.so`) exposing two commands:

- **`import`** — its own builtin because it must not run inside a new function context; it
  replaces the bash function of the same name.
- **`bgCore <subcommand> …`** — the dispatcher that bg-core shell functions defer to when it is
  present, falling back to their pure-bash implementations when it is not.

Accelerated areas: object system (`_bgclassCall`, `ConstructObject`, `DeclareClassEnd`,
`_classUpdateVMT`, `Object_getIndexes`, `IsAnObjRef`), JSON (`Object_toJSON`, `Object_fromJSON`,
`ConstructObjectFromJson`, `arrayToJSON`), INI (`iniParamGet`, `iniParamSet`), templates
(`templateExpand`, `templateExpandStr`, `templateFind`), manifest and path lookup
(`manifestGet`, `findInLibPaths`, `fsExpandFiles`, `pathGetCommon`), value return
(`outputValue`, `varOutput`), and debugger introspection (`scopeToJSON`, `dbgVars`,
`ShellContext_dump`).

Source layout: `bgCore.c` (dispatch) plus `lib/bg_bashAPI.c` (a C API over bash's internals),
`bg_objects.c`, `bg_json.c`, `bg_ini.c`, `bg_templates.c`, `bg_manifest.c`, `bg_import.c`,
`bg_misc.c`, `bg_debug.c`, `BGString.c`, `BGFileLines.c`.

Build: `./configure && make` (configure installs build deps and generates the Makefile from the
host's `/usr/lib/bash/Makefile.inc`); output lands in `./bin/`. `make install` copies to the
host's bash loadables folder. `bg-dev pkg build deb|rpm` packages it.

> The project README's `bg-dev pkgBuild [deb|rpm]` is stale — the current form is
> `bg-dev pkg build [deb|rpm]`.

---

## 4. Where to look next

- Per-project agent instructions: [bg-core/SKILLS.md](bg-core/SKILLS.md),
  [bg-dev/SKILLS.md](bg-dev/SKILLS.md)
- Tutorials with worked examples: [bg-core/readme.md](bg-core/readme.md),
  [bg-dev/readme.md](bg-dev/readme.md)
- Coding idioms: `man 7 bgBashIdioms` (source: [bg-core/man7/bgBashIdioms.7](bg-core/man7/bgBashIdioms.7))
- Doc-comment syntax: `man 5 bgfuncman` (source block in
  [bg-dev/lib/bg_funcman.sh](bg-dev/lib/bg_funcman.sh))
