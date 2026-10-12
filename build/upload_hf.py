"""上传镜像 zip 到 HuggingFace 数据集仓库（内置镜像源 hf-mirror.com / huggingface.co 使用）。

前置：
    pip install huggingface_hub
    setx HF_TOKEN hf_xxx            # HF 网站 Settings → Access Tokens → New token（write 权限）
用法：
    python build/upload_hf.py <image.zip> [--repo SongLiKod/stararm-images] [--file <name>]
    python build/upload_hf.py <image.zip> --check   # 仅校验 token 与目标仓库（不上传）
"""
import argparse
import os
import sys
from pathlib import Path


def fail(message: str, code: int = 1) -> "NoReturn":  # type: ignore[valid-type]
    print(f"[hf] {message}", file=sys.stderr)
    raise SystemExit(code)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload image zip to HuggingFace dataset repo")
    parser.add_argument("zip_path", help="镜像 zip 路径")
    parser.add_argument("--repo", default="SongLiKod/stararm-images", help="HF 数据集仓库 id")
    parser.add_argument("--file", default=None, help="仓库内文件名（默认 zip 文件名）")
    parser.add_argument("--check", action="store_true", help="只校验 token/仓库可达，不上传")
    args = parser.parse_args()

    try:
        from huggingface_hub import HfApi
    except ImportError:
        fail("缺少 huggingface_hub，请先执行: pip install huggingface_hub", 2)

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        fail("未设置 HF_TOKEN 环境变量（huggingface.co → Settings → Access Tokens → New token，勾选 write）", 3)

    api = HfApi(token=token)
    try:
        who = api.whoami()
    except Exception as exc:  # noqa: BLE001
        fail(f"token 无效或不可用: {exc}", 4)
    print(f"[hf] authenticated as {who.get('name', '?')}")

    try:
        api.create_repo(args.repo, repo_type="dataset", exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        fail(f"无法创建/访问数据集仓库 {args.repo}: {exc}", 5)
    print(f"[hf] dataset repo ok: {args.repo}")

    if args.check:
        print("[hf] check ok (no upload)")
        return 0

    zip_path = Path(args.zip_path)
    if not zip_path.is_file():
        fail(f"文件不存在: {zip_path}", 6)
    file_in_repo = args.file or zip_path.name
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"[hf] uploading {zip_path.name} ({size_mb:.1f} MB) -> {args.repo}@main/{file_in_repo} ...")
    try:
        api.upload_file(
            path_or_fileobj=str(zip_path),
            path_in_repo=file_in_repo,
            repo_id=args.repo,
            repo_type="dataset",
            commit_message=f"Add image {file_in_repo}",
        )
    except Exception as exc:  # noqa: BLE001
        fail(f"上传失败: {exc}", 7)
    print(f"[hf] done: https://huggingface.co/datasets/{args.repo}/resolve/main/{file_in_repo}")
    print("[hf] sources now serving it: huggingface.co + hf-mirror.com")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
