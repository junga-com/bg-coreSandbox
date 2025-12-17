# usage: python coreDepAnalysis.py <codeFolderPath> 
# output: list of external dependencies used in the code folder, one per line
#         line format: <dependencyType> <dependencyName>
#         dependencyType: shellFile|awkFile|command
#         dependencyType: shellFile|awkFile
# dependencies are extracted from shell scripts and awk files in the code folder. shell scripts use source or . or 
# an import statement idiom to include other shell scripts
#        import [options] <filename>  ;$L1;$L2  # import statement idiom. the path is determined at runtime but this tool assumes the imported file is in the same folder as the importing script
# Code Files:
#    <moduleName>.<ext>: library files have extenstions indicating their language
#    <commandName>     : commands do not have extensions but their langaguage are identified by shebang lines
#    <PlugoinName>.<PluginType> : plugins modules have extensions indicating their plugin type
# How this tool works:
#   1. identify code files in the code folder
#   2. parse each code file to create the following lists
#      a) commands/functions provided by the file
#      b) files/modules included by the file 
#      c) commands/functions used by the file
#   3. create a list of files/modules that are included but not provided in the code folder
#   4. create a list of commands/functions that are used but not provided in the code folder
#   5. classify the missing files/modules and commands/functions into dependency types
#      a) shellFile: shell scripts included but not provided in the code folder
#      b) awkFile: awk files included but not provided in the code folder
#      c) command: commands/functions used but not provided in the code folder
# Note: this tool does not handle dynamic imports or command invocations where the command name is constructed at runtime

from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Set, Dict  # add Dict


# --- file identification ------------------------------------------------------

_SHEBANG_RE = re.compile(r"^#!\s*(?P<path>\S+)(?P<rest>.*)$")

def _read_first_line(p: Path) -> str:
	try:
		with p.open("r", encoding="utf-8", errors="replace") as f:
			return f.readline().strip()
	except OSError:
		return ""


def _is_awk_shebang(line1: str) -> bool:
	m = _SHEBANG_RE.match(line1)
	if not m:
		return False
	s = (m.group("path") + " " + (m.group("rest") or "")).lower()
	return ("awk" in s) or ("gawk" in s) or ("nawk" in s) or ("mawk" in s)


def _is_shell_shebang(line1: str) -> bool:
	m = _SHEBANG_RE.match(line1)
	if not m:
		return False
	s = (m.group("path") + " " + (m.group("rest") or "")).lower()
	# common: /bin/sh, /usr/bin/env bash, bash -e, etc.
	return ("bash" in s) or re.search(r"(^|[\s/])sh(\s|$)", s) is not None


def _classify_file(p: Path) -> Optional[str]:
	"""
	Returns: "shell" | "awk" | None
	"""
	ext = p.suffix.lower()
	if ext == ".awk":
		return "awk"
	if ext == ".sh":
		return "shell"

	line1 = _read_first_line(p)
	if _is_awk_shebang(line1):
		return "awk"
	if _is_shell_shebang(line1):
		return "shell"
	return None


def _is_command_file(p: Path) -> bool:
	# "commands do not have extensions but their language are identified by shebang lines"
	return p.suffix == "" and _read_first_line(p).startswith("#!")


# --- parsing: includes --------------------------------------------------------

_SOURCE_RE = re.compile(r"^\s*(?:source|\.)\s+([^;\s]+)")
_AWK_INCLUDE_RE = re.compile(r'@include\s+"([^"]+)"')

def _strip_quotes(s: str) -> str:
	s = s.strip()
	if (len(s) >= 2) and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
		return s[1:-1]
	return s


def _looks_dynamic_or_abs(s: str) -> bool:
	# dynamic: variables, command substitution, globs; keep it simple
	return (
		s.startswith("/")
		or "$" in s
		or "`" in s
		or "$(" in s
		or "*" in s
		or "?" in s
		or "[" in s
	)


def _resolve_include(code_root: Path, from_file: Path, raw: str) -> Optional[Path]:
	"""
	Resolve a referenced include target to an existing file within code_root.
	Returns absolute Path if resolved, else None.
	"""
	name = _strip_quotes(raw)
	if not name or _looks_dynamic_or_abs(name):
		return None

	from_dir = from_file.parent

	candidates: List[Path] = []
	if "/" in name:
		candidates.append((from_dir / name).resolve())
	else:
		candidates.append((from_dir / name).resolve())
		# try common extensions if missing
		if not name.endswith(".sh"):
			candidates.append((from_dir / f"{name}.sh").resolve())
		if not name.endswith(".awk"):
			candidates.append((from_dir / f"{name}.awk").resolve())

	try:
		code_root_resolved = code_root.resolve()
	except OSError:
		code_root_resolved = code_root

	for c in candidates:
		try:
			if c.exists() and c.is_file():
				# must be inside code_root
				c_rel = c.relative_to(code_root_resolved)
				_ = c_rel  # just to validate
				return c
		except Exception:
			pass
	return None


# --- parsing: provided symbols ------------------------------------------------

_SH_FUNC1_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")
_SH_FUNC2_RE = re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\))?\s*\{")
_AWK_FUNC_RE = re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")

def _extract_provided_functions(kind: str, text: str) -> Set[str]:
	out: Set[str] = set()
	for line in text.splitlines():
		if kind == "shell":
			m = _SH_FUNC1_RE.match(line) or _SH_FUNC2_RE.match(line)
			if m:
				out.add(m.group(1))
		elif kind == "awk":
			m = _AWK_FUNC_RE.match(line)
			if m:
				out.add(m.group(1))
	return out


# --- parsing: used commands (shell, heuristic) --------------------------------

_SHELL_KEYWORDS = {
	"if", "then", "elif", "else", "fi",
	"for", "select", "while", "until", "do", "done",
	"case", "esac", "in",
	"function", "time", "coproc",
	"{" , "}", "!", "[[", "[", "]]", "]", "(", ")",
}

# keep this conservative; we want "external commands", not shell plumbing
_SHELL_BUILTINS = {
	":", ".", "source", "return", "local", "declare", "typeset", "export", "readonly",
	"unset", "shift", "getopts", "eval", "exec", "trap", "set", "shopt",
	"alias", "unalias", "bg", "fg", "jobs", "wait", "disown",
	"cd", "pwd", "pushd", "popd", "dirs",
	"echo", "printf", "read", "test", "true", "false", "help", "type",
}

def _strip_shell_comment(line: str) -> str:
	# minimal state machine for quotes; good enough for dependency scan
	out = []
	in_s = False
	in_d = False
	esc = False
	for ch in line:
		if esc:
			out.append(ch)
			esc = False
			continue
		if ch == "\\" and not in_s:
			out.append(ch)
			esc = True
			continue
		if ch == "'" and not in_d:
			in_s = not in_s
			out.append(ch)
			continue
		if ch == '"' and not in_s:
			in_d = not in_d
			out.append(ch)
			continue
		if ch == "#" and not in_s and not in_d:
			break
		out.append(ch)
	return "".join(out).rstrip()


def _parse_import_target(line: str) -> Optional[str]:
	"""
	Parse: import [options] <filename> ;$L1;$L2
	where [options] are tokens starting with '-'.
	Returns the raw filename token (may be quoted in source), or None.
	"""
	line = _strip_shell_comment(line)
	if not re.match(r"^\s*import\b", line):
		return None

	# Ignore everything after the first ';' (the idiom appends ';$L1;$L2')
	head = line.split(";", 1)[0]

	try:
		toks = shlex.split(head, posix=True)
	except Exception:
		return None
	if not toks or toks[0] != "import":
		return None

	i = 1
	while i < len(toks) and toks[i].startswith("-"):
		i += 1
	if i >= len(toks):
		return None
	return toks[i]


# --- main analysis ------------------------------------------------------------

@dataclass(frozen=True)
class CodeFile:
	path: Path          # absolute
	kind: str           # "shell" | "awk"
	rel: str            # path relative to code_root (posix)


def _iter_code_files(code_root: Path) -> Iterator[CodeFile]:
	for p in code_root.rglob("*"):
		if not p.is_file():
			continue
		kind = _classify_file(p)
		if not kind:
			continue
		rel = p.resolve().relative_to(code_root.resolve()).as_posix()
		yield CodeFile(path=p.resolve(), kind=kind, rel=rel)


def _read_text(p: Path) -> str:
	try:
		return p.read_text(encoding="utf-8", errors="replace")
	except OSError:
		return ""


def _build_file_indexes(code_root: Path) -> tuple[Set[str], Dict[str, List[str]]]:
	"""
	Returns:
	  all_relpaths: set of all file paths under code_root, relative (posix)
	  by_basename: basename -> list of relpaths
	"""
	all_relpaths: Set[str] = set()
	by_basename: Dict[str, List[str]] = {}
	root = code_root.resolve()

	for p in root.rglob("*"):
		if not p.is_file():
			continue
		rel = p.relative_to(root).as_posix()
		all_relpaths.add(rel)
		by_basename.setdefault(p.name, []).append(rel)

	return all_relpaths, by_basename


def _exists_anywhere_under_root(
	code_root: Path,
	all_relpaths: Set[str],
	by_basename: Dict[str, List[str]],
	raw: str,
) -> bool:
	"""
	If 'raw' names a non-dynamic, non-absolute file that exists anywhere under code_root, return True.
	Heuristic:
	  - if raw contains '/', treat it as a relative path under code_root (after stripping leading ./)
	  - else treat it as a basename and look it up in by_basename (also try adding .sh/.awk)
	"""
	name = _strip_quotes(raw)
	if not name or _looks_dynamic_or_abs(name):
		return False

	# normalize leading './'
	while name.startswith("./"):
		name = name[2:]

	if "/" in name:
		return name in all_relpaths

	# basename lookup
	if name in by_basename:
		return True
	if not name.endswith(".sh") and f"{name}.sh" in by_basename:
		return True
	if not name.endswith(".awk") and f"{name}.awk" in by_basename:
		return True
	return False


def main(argv: Sequence[str]) -> int:
	if len(argv) != 2:
		print("usage: python coreDepAnalysis.py <codeFolderPath>", file=sys.stderr)
		return 2

	code_root = Path(argv[1]).expanduser()
	if not code_root.exists() or not code_root.is_dir():
		print(f"error: not a folder: {code_root}", file=sys.stderr)
		return 2

	files = list(_iter_code_files(code_root))

	# Provided inventory: only file/modules
	provided_files_rel: Set[str] = {cf.rel for cf in files}

	# NEW: index *all* files in folder tree so subfolder files satisfy deps
	all_relpaths, by_basename = _build_file_indexes(code_root)

	# Gather unsatisfied includes (file/module level only)
	missing_shell_files: Set[str] = set()
	missing_awk_files: Set[str] = set()

	for cf in files:
		text = _read_text(cf.path)

		for raw_line in text.splitlines():
			# import [options] <filename> ;$L1;$L2
			raw = _parse_import_target(raw_line)
			if raw:
				res = _resolve_include(code_root, cf.path, raw)
				if res is None:
					# fallback: if it exists anywhere under code_root, it's internal (do not report)
					if not _exists_anywhere_under_root(code_root, all_relpaths, by_basename, raw):
						name = _strip_quotes(raw)
						if name.endswith(".awk"):
							missing_awk_files.add(name)
						else:
							missing_shell_files.add(name)
				else:
					rel = res.relative_to(code_root.resolve()).as_posix()
					if rel not in provided_files_rel:
						# still internal if it exists anywhere under root (e.g., non-codefile deps)
						if not _exists_anywhere_under_root(code_root, all_relpaths, by_basename, rel):
							if rel.endswith(".awk"):
								missing_awk_files.add(rel)
							else:
								missing_shell_files.add(rel)

			# source / .
			m = _SOURCE_RE.match(raw_line)
			if m:
				raw2 = m.group(1)
				res = _resolve_include(code_root, cf.path, raw2)
				if res is None:
					if not _exists_anywhere_under_root(code_root, all_relpaths, by_basename, raw2):
						name = _strip_quotes(raw2)
						if name.endswith(".awk"):
							missing_awk_files.add(name)
						else:
							missing_shell_files.add(name)
				else:
					rel = res.relative_to(code_root.resolve()).as_posix()
					if rel not in provided_files_rel:
						if not _exists_anywhere_under_root(code_root, all_relpaths, by_basename, rel):
							if rel.endswith(".awk"):
								missing_awk_files.add(rel)
							else:
								missing_shell_files.add(rel)

			# awk @include "..."
			for inc in _AWK_INCLUDE_RE.findall(raw_line):
				res = _resolve_include(code_root, cf.path, inc)
				if res is None:
					if not _exists_anywhere_under_root(code_root, all_relpaths, by_basename, inc):
						name = _strip_quotes(inc)
						if name.endswith(".sh"):
							missing_shell_files.add(name)
						else:
							missing_awk_files.add(name)
				else:
					rel = res.relative_to(code_root.resolve()).as_posix()
					if rel not in provided_files_rel:
						if not _exists_anywhere_under_root(code_root, all_relpaths, by_basename, rel):
							if rel.endswith(".sh"):
								missing_shell_files.add(rel)
							else:
								missing_awk_files.add(rel)

	# Output: unique, sorted
	for name in sorted(missing_shell_files):
		print(f"shellFile {name}")
	for name in sorted(missing_awk_files):
		print(f"awkFile {name}")

	return 0


if __name__ == "__main__":
	raise SystemExit(main(sys.argv))
