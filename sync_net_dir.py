#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import fnmatch
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple, Dict, Set

try:
    import yaml
except ImportError:
    print("Missing dependency: pyyaml. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

IS_WINDOWS = os.name == "nt"

def _to_long_path(p: str) -> str:
    """Return Windows long-path prefixed path."""
    if not IS_WINDOWS:
        return p
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC" + p[1:]
    return "\\\\?\\" + p

@dataclass
class Excludes:
    """Exclude rules container."""
    root_dirs: Set[str]
    recursive_dirs: Set[str]
    file_patterns: List[str]
    specific_paths: List[str]

@dataclass
class JobConfig:
    """Job configuration holder."""
    source_dir: Path
    dest_dir: Path
    excludes: Excludes

    @staticmethod
    def from_yaml(path: Path) -> "JobConfig":
        """Load configuration from YAML."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for key in ("source_dir", "dest_dir"):
            if key not in data or not data[key]:
                raise ValueError(f"Missing required key: {key}")
        excl = data.get("excludes", {}) or {}
        root_dirs = set(map(str.lower, (excl.get("root_dirs") or [])))
        recursive_dirs = set(map(str.lower, (excl.get("recursive_dirs") or [])))
        file_patterns = list(excl.get("file_patterns") or [])
        specific_paths = [str(p).replace("/", "\\").lower() for p in (excl.get("specific_paths") or [])]
        return JobConfig(
            source_dir=Path(data["source_dir"]),
            dest_dir=Path(data["dest_dir"]),
            excludes=Excludes(
                root_dirs=root_dirs,
                recursive_dirs=recursive_dirs,
                file_patterns=file_patterns,
                specific_paths=specific_paths,
            ),
        )

@dataclass
class PlanItem:
    """Planned file operation."""
    action: str  # "ADD", "UPDATE", "SKIP", "EXCLUDE"
    src: Path
    dst: Path
    reason: str = ""

class SyncPlanner:
    """Plan sync operations using size+mtime."""
    def __init__(self, cfg: JobConfig, verbose: bool = False):
        """Initialize planner."""
        self.cfg = cfg
        self.verbose = verbose
        self.src_root = cfg.source_dir.resolve()
        self.dst_root = cfg.dest_dir.resolve()
        self._root_excl = cfg.excludes.root_dirs
        self._rec_excl = cfg.excludes.recursive_dirs
        self._file_patterns = [p.lower() for p in cfg.excludes.file_patterns]
        self._specific_excl = cfg.excludes.specific_paths

    def plan(self) -> List[PlanItem]:
        """Build the sync plan."""
        if not self.src_root.exists():
            raise FileNotFoundError(f"Source not found: {self.src_root}")
        items: List[PlanItem] = []

        for dirpath, dirnames, filenames in os.walk(self._long(self.src_root)):
            dirpath_path = Path(self._short(Path(dirpath)))
            rel_dir = dirpath_path.relative_to(self.src_root)

            # Specific path pruning (e.g., 'scripts\\output'); record exclusion
            if self._is_under_specific(rel_dir):
                items.append(PlanItem(
                    "EXCLUDE",
                    dirpath_path,
                    self.dst_root / rel_dir,
                    reason="specific_path"
                ))
                dirnames[:] = []
                filenames[:] = []
                continue

            # Root-only excludes: remove from traversal and record them
            if rel_dir == Path("."):
                lowered = [d.lower() for d in dirnames]
                keep, removed = [], []
                for name, low in zip(dirnames, lowered):
                    if low in self._root_excl:
                        removed.append(name)
                    else:
                        keep.append(name)
                if removed:
                    for r in removed:
                        src_d = dirpath_path / r
                        dst_d = self.dst_root / r
                        items.append(PlanItem("EXCLUDE", src_d, dst_d, reason="root_dir"))
                dirnames[:] = keep

            # Recursive excludes: remove from traversal and record them
            if dirnames:
                lowered = [d.lower() for d in dirnames]
                keep, removed = [], []
                for name, low in zip(dirnames, lowered):
                    if low in self._rec_excl:
                        removed.append(name)
                    else:
                        keep.append(name)
                if removed:
                    for r in removed:
                        src_d = dirpath_path / r
                        dst_d = self.dst_root / rel_dir / r
                        items.append(PlanItem("EXCLUDE", src_d, dst_d, reason="recursive_dir"))
                dirnames[:] = keep

            # Files in this directory
            for fname in filenames:
                src_file = Path(dirpath_path) / fname
                rel_file = src_file.relative_to(self.src_root)
                dst_file = self.dst_root / rel_file

                if self._is_file_excluded(fname):
                    items.append(PlanItem("EXCLUDE", src_file, dst_file, reason="pattern"))
                    continue

                act, reason = self._decide(src_file, dst_file)
                items.append(PlanItem(act, src_file, dst_file, reason=reason))

        return items

    def _decide(self, src: Path, dst: Path) -> Tuple[str, str]:
        """Decide action for a file."""
        try:
            s_stat = os.stat(self._long(src))
        except OSError as e:
            return ("EXCLUDE", f"unreadable: {e}")
        if not dst.exists():
            return ("ADD", "missing")
        try:
            d_stat = os.stat(self._long(dst))
        except OSError as e:
            return ("UPDATE", f"dst unreadable: {e}")
        size_same = s_stat.st_size == d_stat.st_size
        mtime_same = abs(s_stat.st_mtime - d_stat.st_mtime) <= 2
        if size_same and mtime_same:
            return ("SKIP", "same size+mtime")
        return ("UPDATE", f"size {'=' if size_same else '≠'}, mtime {'=' if mtime_same else '≠'}")

    def _is_file_excluded(self, name: str) -> bool:
        """Return True if file matches excluded patterns."""
        n = name.lower()
        for pat in self._file_patterns:
            if fnmatch.fnmatch(n, pat):
                return True
        return False

    def _is_under_specific(self, rel_dir: Path) -> bool:
        """Return True if rel_dir equals/starts with any specific excluded path."""
        if not self._specific_excl:
            return False
        s = self._rel_str(rel_dir)
        for sp in self._specific_excl:
            if s == sp or s.startswith(sp + "\\"):
                return True
        return False

    @staticmethod
    def _long(p: Path | str) -> str:
        """Return long-path form."""
        return _to_long_path(str(p))

    @staticmethod
    def _short(p: Path) -> str:
        """Strip long-path prefix for display."""
        s = str(p)
        if IS_WINDOWS and s.startswith("\\\\?\\UNC\\"):
            return "\\" + s[7:]
        if IS_WINDOWS and s.startswith("\\\\?\\"):
            return s[4:]
        return s

    @staticmethod
    def _rel_str(p: Path) -> str:
        """Return lowercase relative path with backslashes."""
        return str(p).replace("/", "\\").lower()

class SyncApplier:
    """Apply planned file copies atomically."""
    def __init__(self, preserve_mtime: bool = True):
        """Initialize applier."""
        self.preserve_mtime = preserve_mtime

    def apply(self, items: Iterable[PlanItem]) -> None:
        """Execute adds and updates."""
        for it in items:
            if it.action in ("SKIP", "EXCLUDE"):
                continue
            it.dst.parent.mkdir(parents=True, exist_ok=True)
            temp_path = it.dst.with_suffix(it.dst.suffix + ".part")
            try:
                shutil.copyfile(_to_long_path(str(it.src)), _to_long_path(str(temp_path)))
                if self.preserve_mtime:
                    s_stat = os.stat(_to_long_path(str(it.src)))
                    os.utime(_to_long_path(str(temp_path)), (s_stat.st_atime, s_stat.st_mtime))
                os.replace(_to_long_path(str(temp_path)), _to_long_path(str(it.dst)))
            except PermissionError:
                try:
                    if os.path.exists(_to_long_path(str(temp_path))):
                        os.remove(_to_long_path(str(temp_path)))
                finally:
                    raise
            except OSError:
                try:
                    if os.path.exists(_to_long_path(str(temp_path))):
                        os.remove(_to_long_path(str(temp_path)))
                finally:
                    raise

def _fmt_list(lst: Iterable[str]) -> str:
    """Return comma-separated list or '(none)'."""
    seq = list(lst)
    return ", ".join(seq) if seq else "(none)"

def format_config_summary(cfg: JobConfig) -> str:
    """Return a brief config summary."""
    ex = cfg.excludes
    lines = [
        f"Source: {cfg.source_dir}",
        f"Dest  : {cfg.dest_dir}",
        "Excludes:",
        f"  root_dirs     : {_fmt_list(sorted(ex.root_dirs))}",
        f"  recursive_dirs: {_fmt_list(sorted(ex.recursive_dirs))}",
        f"  specific_paths: {_fmt_list(ex.specific_paths)}",
        f"  file_patterns : {_fmt_list(ex.file_patterns)}",
        ""
    ]
    return "\n".join(lines)

def format_plan(items: List[PlanItem], src_root: Path | None = None, dst_root: Path | None = None, compact: bool = False) -> str:
    """Create human-readable plan summary."""
    groups: Dict[str, List[PlanItem]] = {"ADD": [], "UPDATE": [], "SKIP": [], "EXCLUDE": []}
    for it in items:
        groups.setdefault(it.action, []).append(it)

    def rel(p: Path, root: Path | None) -> str:
        try:
            return str(p.relative_to(root)) if root else str(p)
        except ValueError:
            return str(p)

    lines: List[str] = []
    total = sum(len(v) for v in groups.values())

    if compact:
        if src_root:
            lines.append(f"Source: {src_root}")
        if dst_root:
            lines.append(f"Dest  : {dst_root}")
        lines.append(
            f"Plan  : add {len(groups['ADD'])} | update {len(groups['UPDATE'])} | "
            f"skip {len(groups['SKIP'])} | exclude {len(groups['EXCLUDE'])}"
        )
        lines.append("")

        def block(title: str, key: str):
            rows = groups.get(key, [])
            lines.append(f"{title} ({len(rows)})")
            for it in rows:
                lines.append(f"  - {rel(it.src, src_root)} [{it.reason}]")
            lines.append("")

        block("ADDED", "ADD")
        block("UPDATED", "UPDATE")
        block("SKIPPED (already up-to-date)", "SKIP")
        block("EXCLUDED (by pattern or pruned dir)", "EXCLUDE")

        lines.append(
            f"Summary: total {total} | add {len(groups['ADD'])} | update {len(groups['UPDATE'])} | "
            f"skip {len(groups['SKIP'])} | exclude {len(groups['EXCLUDE'])}"
        )
        return "\n".join(lines)

    def block_verbose(title: str, key: str):
        rows = groups.get(key, [])
        lines.append(f"{title} ({len(rows)})")
        for it in rows:
            lines.append(f"  - {key:7} {it.src}  →  {it.dst}  [{it.reason}]")
        lines.append("")

    block_verbose("ADDED", "ADD")
    block_verbose("UPDATED", "UPDATE")
    block_verbose("SKIPPED (already up-to-date)", "SKIP")
    block_verbose("EXCLUDED (by pattern or pruned dir)", "EXCLUDE")

    lines.append(
        f"Summary: total {total} | add {len(groups['ADD'])} | update {len(groups['UPDATE'])} | "
        f"skip {len(groups['SKIP'])} | exclude {len(groups['EXCLUDE'])}"
    )
    return "\n".join(lines)

def main():
    """Parse args, plan, and optionally apply."""
    parser = argparse.ArgumentParser(description="Mirror a server app directory to a local directory (read-only from network).")
    parser.add_argument("--config", required=True, help="Path to YAML config (one job).")
    parser.add_argument("--apply", action="store_true", help="Apply changes (copy). Omit for dry-run.")
    parser.add_argument("--verbose", action="store_true", help="Verbose output.")
    parser.add_argument("--compact", action="store_true", help="Compact output: show relative paths and summarize roots.")
    args = parser.parse_args()

    try:
        cfg = JobConfig.from_yaml(Path(args.config))
    except Exception as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(2)

    # Brief config summary at the top
    if not args.compact:
        print(format_config_summary(cfg))

    planner = SyncPlanner(cfg, verbose=args.verbose)
    try:
        plan = planner.plan()
    except Exception as e:
        print(f"Planning failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(format_plan(plan, src_root=planner.src_root, dst_root=planner.dst_root, compact=args.compact))

    if not args.apply:
        return

    to_apply = [it for it in plan if it.action in ("ADD", "UPDATE")]
    applier = SyncApplier(preserve_mtime=True)
    try:
        applier.apply(to_apply)
    except PermissionError as e:
        print(f"Copy aborted (permission/lock error): {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Copy aborted (I/O error): {e}", file=sys.stderr)
        sys.exit(1)

    print("Apply complete.")

if __name__ == "__main__":
    main()
