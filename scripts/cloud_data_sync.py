from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SyncResult:
    copied_files: int
    copied_bytes: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed: "
            + " ".join(cmd)
            + "\nstdout:\n"
            + (proc.stdout or "")
            + "\nstderr:\n"
            + (proc.stderr or "")
        )
    return proc


def _ensure_kaggle_cli() -> None:
    _run(["kaggle", "--version"])


def _slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def _write_dataset_metadata(stage_root: Path, dataset_id: str) -> None:
    if "/" not in dataset_id:
        raise ValueError("dataset_id must use owner/slug format, e.g. le1ma1/leimai-oracle-data")
    slug = dataset_id.split("/", 1)[1].strip()
    title = _slug_to_title(slug) or "LeiMai Oracle Dataset"
    payload = (
        "{\n"
        f'  "title": "{title}",\n'
        f'  "id": "{dataset_id}",\n'
        '  "licenses": [\n'
        '    {\n'
        '      "name": "CC0-1.0"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )
    (stage_root / "dataset-metadata.json").write_text(payload, encoding="utf-8")


def _copy_tree(src: Path, dst: Path) -> SyncResult:
    copied_files = 0
    copied_bytes = 0
    for root, _, files in os.walk(src):
        root_path = Path(root)
        rel = root_path.relative_to(src)
        out_dir = dst / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            in_file = root_path / name
            out_file = out_dir / name
            shutil.copy2(in_file, out_file)
            copied_files += 1
            try:
                copied_bytes += out_file.stat().st_size
            except OSError:
                pass
    return SyncResult(copied_files=copied_files, copied_bytes=copied_bytes)


def _resolve_source_rel(repo_root: Path, source: Path) -> Path:
    try:
        return source.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return Path(source.name)


def cmd_push(args: argparse.Namespace) -> int:
    _ensure_kaggle_cli()
    repo_root = _repo_root()
    source = Path(args.source).resolve() if args.source else (repo_root / "engine" / "data" / "raw")
    if not source.exists():
        raise FileNotFoundError(f"Source path does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source}")

    dataset_id = str(args.dataset or os.environ.get("KAGGLE_DATASET_ID") or "").strip()
    if not dataset_id:
        raise ValueError("dataset id is required. Use --dataset or set KAGGLE_DATASET_ID")

    with tempfile.TemporaryDirectory(prefix="lmo_kaggle_push_") as tmp:
        stage = Path(tmp)
        source_rel = _resolve_source_rel(repo_root=repo_root, source=source)
        staged_source = stage / source_rel
        staged_source.parent.mkdir(parents=True, exist_ok=True)
        stats = _copy_tree(source, staged_source)
        _write_dataset_metadata(stage, dataset_id=dataset_id)

        message = str(args.message or "update dataset from local engine data").strip()
        version_cmd = ["kaggle", "datasets", "version", "-p", str(stage), "-m", message, "-r", "zip"]
        proc = subprocess.run(version_cmd, text=True, capture_output=True, check=False)
        if proc.returncode != 0 and bool(args.create_if_missing):
            create_cmd = ["kaggle", "datasets", "create", "-p", str(stage), "-r", "zip"]
            _run(create_cmd)
        elif proc.returncode != 0:
            raise RuntimeError(
                "kaggle datasets version failed\nstdout:\n"
                + (proc.stdout or "")
                + "\nstderr:\n"
                + (proc.stderr or "")
            )

        print(
            f"[push_done] dataset={dataset_id} files={stats.copied_files} bytes={stats.copied_bytes} "
            f"source={source_rel.as_posix()}"
        )
    return 0


def _auto_detect_extract_root(download_dir: Path) -> Path | None:
    candidates = (
        download_dir / "engine" / "artifacts",
        download_dir / "engine" / "data" / "raw",
        download_dir / "engine",
        download_dir / "artifacts",
        download_dir / "data",
    )
    for item in candidates:
        if item.exists():
            return item
    return None


def cmd_pull(args: argparse.Namespace) -> int:
    _ensure_kaggle_cli()
    repo_root = _repo_root()
    dataset_id = str(args.dataset or os.environ.get("KAGGLE_DATASET_ID") or "").strip()
    if not dataset_id:
        raise ValueError("dataset id is required. Use --dataset or set KAGGLE_DATASET_ID")

    target_root = Path(args.target).resolve() if args.target else repo_root
    target_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lmo_kaggle_pull_") as tmp:
        download_dir = Path(tmp) / "download"
        download_dir.mkdir(parents=True, exist_ok=True)

        _run(["kaggle", "datasets", "download", "-d", dataset_id, "-p", str(download_dir), "--unzip"])

        if args.extract_root:
            extract_src = download_dir / args.extract_root
            if not extract_src.exists():
                raise FileNotFoundError(f"extract_root not found in dataset payload: {args.extract_root}")
        else:
            extract_src = _auto_detect_extract_root(download_dir)
            if extract_src is None:
                raise RuntimeError("Unable to auto-detect extract root in downloaded dataset payload")

        rel = extract_src.relative_to(download_dir)
        dst = target_root / rel
        dst.mkdir(parents=True, exist_ok=True)
        stats = _copy_tree(extract_src, dst)
        print(
            f"[pull_done] dataset={dataset_id} extracted={rel.as_posix()} files={stats.copied_files} "
            f"bytes={stats.copied_bytes} target={dst}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync LeiMai Oracle data/artifacts between local repo and Kaggle dataset."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_push = sub.add_parser("push", help="Upload local data directory to Kaggle dataset version.")
    p_push.add_argument("--dataset", default=None, help="Kaggle dataset id, e.g. le1ma1/leimai-oracle-data")
    p_push.add_argument("--source", default=None, help="Local directory to upload (default: engine/data/raw).")
    p_push.add_argument("--message", default="update dataset from local engine data")
    p_push.add_argument(
        "--create-if-missing",
        action="store_true",
        help="Create dataset if version command fails because dataset does not exist.",
    )
    p_push.set_defaults(func=cmd_push)

    p_pull = sub.add_parser("pull", help="Download dataset and sync payload into local repo.")
    p_pull.add_argument("--dataset", default=None, help="Kaggle dataset id, e.g. le1ma1/leimai-oracle-data")
    p_pull.add_argument("--target", default=None, help="Local target root (default: repo root).")
    p_pull.add_argument(
        "--extract-root",
        default=None,
        help="Optional root path inside dataset zip to copy, e.g. engine/artifacts/optimization/single.",
    )
    p_pull.set_defaults(func=cmd_pull)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
