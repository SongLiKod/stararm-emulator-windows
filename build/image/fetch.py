#!/usr/bin/env python3
"""从 ci.android.com 下载 AOSP 构建产物（免登录，支持断点续传）。

要点（均已实测）：
  * 产物列表: GET  .../builds/submitted/<id>/<target>/latest/raw/BUILD_INFO  (JSON, target.dir_list)
  * 产物下载: GET  .../builds/submitted/<id>/<target>/latest/raw/<name>       (HEAD 不支持 → 404)
  * 断点续传: Range: bytes=<start>-  → 206 + Content-Range: bytes s-e/total
  * 最新成功构建: GET .../builds/branches/<branch>/status.json → targets[].last_known_good_build

用法:
  python3 build/image/fetch.py --branch aosp-android14-gsi \
      --target aosp_cf_arm64_phone-userdebug --list
  python3 build/image/fetch.py --build-id 16571446 --target aosp_cf_arm64_phone-userdebug \
      --out .work --download aosp_cf_arm64_phone-img-16571446.zip otatools.zip
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

RAW = "https://ci.android.com/builds/submitted/{build}/{target}/latest/raw"
STATUS = "https://ci.android.com/builds/branches/{branch}/status.json"
UA = {"User-Agent": "stararm-image-builder/1.0 (+https://github.com/SongLiKod/stararm-emulator-windows)"}


def _open(url: str, headers=None, timeout: float = 90):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def resolve_build_id(branch: str, target: str) -> str:
    with _open(STATUS.format(branch=urllib.parse.quote(branch))) as r:
        data = json.loads(r.read())
    for t in data.get("targets", []):
        if t.get("name") == target and t.get("last_known_good_build"):
            return str(t["last_known_good_build"])
    raise SystemExit(f"[fetch] branch={branch} 没有 target={target} 的成功构建")


def artifact_names(build_id: str, target: str) -> list:
    url = RAW.format(build=build_id, target=urllib.parse.quote(target)) + "/BUILD_INFO"
    with _open(url, timeout=120) as r:
        info = json.loads(r.read())
    return info.get("target", {}).get("dir_list", [])


def remote_size(url: str) -> int:
    with _open(url, headers={"Range": "bytes=0-0"}, timeout=60) as r:
        cr = r.headers.get("Content-Range", "")
        if "/" not in cr:
            raise SystemExit(f"[fetch] 无法获取大小: {url}")
        return int(cr.rsplit("/", 1)[1])


def download(url: str, dest: str, retries: int = 5) -> int:
    total = remote_size(url)
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    attempt = 0
    while True:
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
        if have == total:
            print(f"[fetch] ok  {os.path.basename(dest)}  {total/1024/1024:.1f} MB (已有)")
            return total
        if have > total:
            os.remove(dest)
            have = 0
        start = have
        try:
            req = urllib.request.Request(
                url, headers={**UA, "Range": f"bytes={start}-"})
            with urllib.request.urlopen(req, timeout=180) as r, open(dest, "ab") as f:
                done = start
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if done and (done % (100 << 20)) < (1 << 20):
                        print(f"[fetch]   {os.path.basename(dest)} "
                              f"{done/1024/1024:.0f}/{total/1024/1024:.0f} MB",
                              flush=True)
            size = os.path.getsize(dest)
            if size == total:
                print(f"[fetch] ok  {os.path.basename(dest)}  {total/1024/1024:.1f} MB")
                return total
            raise IOError(f"incomplete {size}/{total}")
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            if attempt > retries:
                raise SystemExit(f"[fetch] 下载失败({url}): {exc}")
            wait = min(2 ** attempt, 30)
            print(f"[fetch] 重试 {attempt}/{retries} ({wait}s): {exc}", flush=True)
            time.sleep(wait)


def main() -> int:
    p = argparse.ArgumentParser(description="Download AOSP CI artifacts from ci.android.com")
    p.add_argument("--branch", default="")
    p.add_argument("--target", required=True)
    p.add_argument("--build-id", default="")
    p.add_argument("--out", default=".work")
    p.add_argument("--download", nargs="*", default=[])
    p.add_argument("--list", action="store_true", help="打印产物清单")
    a = p.parse_args()

    build_id = a.build_id or (resolve_build_id(a.branch, a.target) if a.branch else "")
    if not build_id:
        raise SystemExit("[fetch] 需要 --build-id 或 --branch")
    print(f"[fetch] target={a.target} build_id={build_id}")

    names = artifact_names(build_id, a.target)
    if a.list:
        for n in sorted(names):
            print("  ", n)
        return 0
    if not a.download:
        raise SystemExit("[fetch] 没有要下载的文件（--download <name>... 或 --list）")

    base = RAW.format(build=build_id, target=urllib.parse.quote(a.target))
    for n in a.download:
        if n not in names:
            raise SystemExit(f"[fetch] 产物不存在: {n}（用 --list 查看清单）")
        download(base + "/" + urllib.parse.quote(n), os.path.join(a.out, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
