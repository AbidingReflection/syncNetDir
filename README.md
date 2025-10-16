# SyncNetDir

A command-line utility for synchronizing a **read-only network directory** to a **local working directory**.
Designed for Windows environments (UNC paths supported) with reliable exclusion, atomic copy operations, and long-path handling.

---

## Overview

* **One-way synchronization:** Copies from server → local only (never deletes).
* **Dry-run mode:** Safe preview of planned actions before applying.
* **Detailed exclusions:** Supports root-level, recursive, specific-path, and pattern-based exclusion rules.
* **Atomic writes:** Uses temporary `.part` files to ensure file integrity.
* **Timestamps preserved:** Source modification times are retained.
* **Long path support:** Handles paths exceeding 260 characters automatically.
* **Readable plan summary:** Compact grouped output with counts per action.
* **Batch launcher (`run_sync.bat`):** Automates environment setup, dry-run preview, and confirmation step before apply.

---

## Requirements

* Python **3.10+**
* `PyYAML` package

Install manually if needed:

```bash
pip install PyYAML
```

When using `run_sync.bat`, dependencies are installed automatically.

---

## Configuration

Each sync job is defined in a YAML configuration file.

Example:

```yaml
source_dir: 'C:\Users\decjg\projects\qTest_targeted_data_extractor'
dest_dir: 'C:\Users\decjg\test_out\qTest_targeted_data_extractor'

excludes:
  root_dirs:
    - logs
    - .git
    - venv
    - output

  specific_paths:
    - 'scripts\output'

  recursive_dirs:
    - __pycache__

  file_patterns:
    - '*.log'
    - '*.tmp'
```

### Key Fields

| Field                     | Description                                                      |
| ------------------------- | ---------------------------------------------------------------- |
| `source_dir`              | Source directory (UNC or local).                                 |
| `dest_dir`                | Local mirror target.                                             |
| `excludes.root_dirs`      | Directories excluded only at the root level.                     |
| `excludes.recursive_dirs` | Directories excluded at any depth.                               |
| `excludes.specific_paths` | Specific relative paths (e.g., `scripts\output`) fully excluded. |
| `excludes.file_patterns`  | Wildcard file patterns to skip.                                  |

**Path guidance:**

* Use **single quotes** to preserve Windows-style backslashes.
* Both **UNC** and **local** paths are supported.

---

## Usage

### 1. Dry-run (default)

```bash
python sync_net_dir.py --config configs\sync_job.yaml --compact
```

### 2. Apply changes

```bash
python sync_net_dir.py --config configs\sync_job.yaml --apply
```

### 3. Run via batch launcher

```bash
run_sync.bat
```

This script:

* Creates/activates `.venv` if needed
* Installs dependencies
* Performs a dry-run
* Awaits user confirmation before applying changes

---

## Behavior Summary

| Action      | Description                                                                   |
| ----------- | ----------------------------------------------------------------------------- |
| **ADD**     | File exists in source but not in destination.                                 |
| **UPDATE**  | File differs by size or modification time.                                    |
| **SKIP**    | File already matches.                                                         |
| **EXCLUDE** | File or directory excluded by config (root, recursive, specific, or pattern). |

**Other notes:**

* Skips locked/unreadable files with an error.
* No deletions occur in the destination directory.
* Tolerates up to 2 seconds of timestamp drift between source and destination.

---

## Exit Codes

| Code | Meaning                           |
| ---- | --------------------------------- |
| 0    | Completed successfully            |
| 1    | Copy or permission error          |
| 2    | Configuration or dependency error |

---

## Notes

* Optimized for **predictable**, **safe**, and **repeatable** syncs—not raw speed.
* Ideal for maintaining **read-only mirrors** of network project directories.
