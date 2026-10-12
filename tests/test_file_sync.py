"""共享文件夹双向同步测试：仅传输变化文件、manifest 状态、文件导出。"""
import json

from tools.file_sync import (
    SYNC_MANIFEST, SharedFolderSync, default_sync, export_guest_file,
    pull_file, push_file,
)


def test_host_dir_created_under_home(stararm_home, fake_adb):
    sync = SharedFolderSync(fake_adb)
    host = sync.host_dir()
    assert host.is_dir()
    assert str(stararm_home) in str(host)


def test_sync_push_uploads_new_and_changed_only(stararm_home, fake_adb):
    host = stararm_home / "shared"
    host.mkdir()
    (host / "a.txt").write_text("one", encoding="utf-8")
    sync = SharedFolderSync(fake_adb, host_dir=host)

    pushed = sync.sync_push(5555)
    assert pushed == 1
    assert fake_adb.pushed == [(str(host / "a.txt"), "/sdcard/Shared/a.txt")]
    # manifest 已记录
    manifest = json.loads((host / SYNC_MANIFEST).read_text(encoding="utf-8"))
    assert "a.txt" in manifest and manifest["a.txt"]["size"] == 3

    # 未变化 -> 不重复推送
    fake_adb.pushed.clear()
    assert sync.sync_push(5555) == 0
    assert fake_adb.pushed == []

    # 新增文件 -> 推送
    (host / "b.txt").write_text("two", encoding="utf-8")
    assert sync.sync_push(5555) == 1
    assert fake_adb.pushed[0][1] == "/sdcard/Shared/b.txt"


def test_sync_pull_downloads_new_files(stararm_home, fake_adb):
    host = stararm_home / "shared"
    host.mkdir()
    fake_adb.set_guest_files("/sdcard/Shared", [
        ("/sdcard/Shared/doc.txt", 100, 42),
        ("/sdcard/Shared/sub/deep.txt", 101, 7),
        ("/sdcard/Shared", 102, 0),  # 目录本身，应跳过
    ])
    sync = SharedFolderSync(fake_adb, host_dir=host)

    pulled = sync.sync_pull(5555)
    assert pulled == 2
    # 拉取落盘
    assert (host / "doc.txt").read_text(encoding="utf-8") == "guest:/sdcard/Shared/doc.txt"
    assert (host / "sub" / "deep.txt").is_file()
    manifest = json.loads((host / SYNC_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["doc.txt"] == {"mtime": 100, "size": 42}
    assert manifest["sub/deep.txt"] == {"mtime": 101, "size": 7}

    # 未变化 -> 不重复拉取
    fake_adb.pulled.clear()
    assert sync.sync_pull(5555) == 0
    assert fake_adb.pulled == []


def test_bidirectional_sync(stararm_home, fake_adb):
    host = stararm_home / "shared"
    host.mkdir()
    (host / "up.txt").write_text("up", encoding="utf-8")
    fake_adb.set_guest_files("/sdcard/Shared", [
        ("/sdcard/Shared/down.txt", 200, 5),
    ])
    sync = SharedFolderSync(fake_adb, host_dir=host)
    up, down = sync.sync_bidirectional(5555)
    assert up == 1 and down == 1
    assert (host / "up.txt").is_file()
    assert (host / "down.txt").is_file()


def test_manifest_corrupt_is_ignored(stararm_home, fake_adb):
    host = stararm_home / "shared"
    host.mkdir()
    (host / SYNC_MANIFEST).write_text("not-json{{", encoding="utf-8")
    (host / "x.txt").write_text("x", encoding="utf-8")
    sync = SharedFolderSync(fake_adb, host_dir=host)
    assert sync.sync_push(5555) == 1


def test_push_pull_export_helpers(fake_adb, tmp_path):
    local = tmp_path / "local.bin"
    local.write_bytes(b"bin")
    assert push_file(fake_adb, 5555, str(local), "/sdcard/x.bin") is True
    assert ("push", 5555, str(local), "/sdcard/x.bin") in fake_adb.calls

    out = tmp_path / "out.bin"
    assert pull_file(fake_adb, 5555, "/sdcard/x.bin", str(out)) is True
    assert out.is_file()

    out2 = tmp_path / "exported.bin"
    assert export_guest_file(fake_adb, 5555, "/sdcard/x.bin", str(out2)) is True
    assert out2.is_file()


def test_default_sync_uses_settings_folder(stararm_home, fake_adb):
    from config.settings import SettingsManager
    settings = SettingsManager()
    folder = stararm_home / "custom-shared"
    settings.update(shared_folder=str(folder))
    sync = default_sync(fake_adb, settings)
    assert sync.host_dir() == folder
    assert folder.is_dir()
