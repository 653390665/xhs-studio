"""Douyin extraction pipeline: parsing, resume, delivery and honest failures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.main import app
from backend.app.models import DouyinExtractJob, DouyinWork, User
from backend.app.services import douyin_extract_service as service

FAKE_VIDEO = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'douyin.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    user = User(username="douyin-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    yield session, user
    session.close()


def _media(tmp_path) -> str:
    path = tmp_path / "sample.mp4"
    path.write_bytes(FAKE_VIDEO)
    return str(path)


def _stub_asr(tmp_path) -> str:
    script = tmp_path / "stub_asr.py"
    script.write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                "out = pathlib.Path(sys.argv[2])",
                "out.mkdir(parents=True, exist_ok=True)",
                "segments = [",
                "    {'start': 0.0, 'end': 1.6, 'text': '第一句口播。'},",
                "    {'start': 2.4, 'end': 4.0, 'text': '第二句口播。'},",
                "]",
                "(out / 'transcript.json').write_text(",
                "    json.dumps({'segments': segments}, ensure_ascii=False), encoding='utf-8'",
                ")",
            ]
        ),
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{script}" {{input}} {{outdir}}'
    return command


def test_parse_manifest_json_and_links_and_dedupe():
    payload = {
        "works": [
            {"work_id": "111111", "url": "https://www.douyin.com/video/111111", "title": "A"},
            {"aweme_id": "111111", "url": "https://www.douyin.com/video/111111", "title": "重复"},
            {"url": "https://v.douyin.com/abcDEF/", "caption": "分享文案"},
        ]
    }
    items = service.parse_manifest(json.dumps(payload, ensure_ascii=False))
    assert len(items) == 2
    assert items[0]["work_id"] == "111111"
    assert items[1]["url"].endswith("/abcDEF/")

    links = service.parse_manifest(
        "7.43 复制打开抖音 https://v.douyin.com/xyz123/ 看看\n"
        "https://www.douyin.com/video/222222"
    )
    assert {item["work_id"] for item in links} == {"xyz123", "222222"}


def test_parse_manifest_rejects_empty_input():
    with pytest.raises(service.DouyinExtractError):
        service.parse_manifest("   ")


def test_srt_helpers_and_audit():
    assert service.format_srt_timestamp(3661.5) == "01:01:01,500"
    segments = [
        {"start": 0.0, "end": 1.2, "text": "你好"},
        {"start": 1.2, "end": 3.0, "text": "世界"},
    ]
    srt = service.segments_to_srt(segments)
    assert "00:00:00,000 --> 00:00:01,200" in srt
    assert service.audit_srt(srt) == []

    broken = "1\n00:00:02,000 --> 00:00:01,000\n倒序\n"
    assert service.audit_srt(broken)


def test_safe_filename_strips_illegal_characters():
    assert service.safe_filename('a/b:c*?"d') == "a_b_c___d"


def test_full_pipeline_with_stub_asr_and_resume(db, tmp_path, monkeypatch):
    session, user = db
    monkeypatch.setenv("XHS_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("DOUYIN_EXTRACT_ASR_CMD", _stub_asr(tmp_path))

    media = _media(tmp_path)
    manifest = json.dumps(
        {
            "works": [
                {
                    "work_id": "333333",
                    "url": "https://www.douyin.com/video/333333",
                    "title": "测试作品",
                    "author_name": "测试账号",
                    "media_url": media,
                }
            ]
        },
        ensure_ascii=False,
    )
    job = service.create_job(
        session,
        user,
        source_type="manifest",
        source=manifest,
        account_name="测试账号",
    )
    assert job.total == 1
    job = service.run_job(session, job)

    assert job.status == "completed"
    assert job.completed == 1
    assert job.failed == 0
    assert Path(job.output_dir, "文稿").is_dir()
    text_files = list(Path(job.output_dir, "文稿").glob("*.txt"))
    assert len(text_files) == 1
    assert "第一句口播" in text_files[0].read_text(encoding="utf-8")
    srt_files = list(Path(job.output_dir, "字幕").glob("*.srt"))
    assert len(srt_files) == 1
    assert service.audit_srt(srt_files[0].read_text(encoding="utf-8")) == []
    assert Path(job.output_dir, "作品清单.csv").exists()
    assert Path(job.output_dir, "核对记录.md").exists()
    assert "测试作品" in Path(job.output_dir, "CONTENT_INDEX.md").read_text(encoding="utf-8")

    # 续跑：已完成的作品不重复转写，数量保持稳定。
    job = service.run_job(session, job)
    assert job.completed == 1
    assert len(list(Path(job.output_dir, "文稿").glob("*.txt"))) == 1

    # 跨任务按作品 ID 去重。
    second = service.create_job(
        session,
        user,
        source_type="manifest",
        source=manifest,
        account_name="测试账号",
    )
    assert second.skipped == 1
    assert second.total == 1

    # 但必须能强制重跑：上一版转写实现有缺陷时，去重会让重跑变成"全部跳过"。
    forced = service.create_job(
        session,
        user,
        source_type="manifest",
        source=manifest,
        account_name="测试账号",
        force=True,
    )
    assert forced.skipped == 0
    statuses = session.scalars(
        select(DouyinWork.status).where(DouyinWork.job_id == forced.id)
    ).all()
    assert statuses == ["pending"]


def test_provided_transcript_avoids_asr(db, tmp_path, monkeypatch):
    session, user = db
    monkeypatch.setenv("XHS_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.delenv("DOUYIN_EXTRACT_ASR_CMD", raising=False)

    srt = "1\n00:00:00,000 --> 00:00:02,000\n已有的字幕\n"
    manifest = json.dumps(
        {
            "works": [
                {
                    "work_id": "444444",
                    "title": "自带文稿",
                    "transcript": "已有的口播稿",
                    "srt": srt,
                }
            ]
        },
        ensure_ascii=False,
    )
    job = service.create_job(session, user, source_type="manifest", source=manifest)
    job = service.run_job(session, job)

    assert job.status == "completed"
    assert job.completed == 1
    work = session.query(DouyinWork).filter_by(job_id=job.id).one()
    assert work.transcript_source == "provided"
    assert list(Path(job.output_dir, "字幕").glob("*.srt"))


def test_missing_asr_fails_instead_of_faking_transcript(db, tmp_path, monkeypatch):
    session, user = db
    monkeypatch.setenv("XHS_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.delenv("DOUYIN_EXTRACT_ASR_CMD", raising=False)
    monkeypatch.setattr(service.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(service.shutil, "which", lambda name: None)

    manifest = json.dumps(
        {"works": [{"work_id": "555555", "media_url": _media(tmp_path)}]},
        ensure_ascii=False,
    )
    job = service.create_job(session, user, source_type="manifest", source=manifest)
    job = service.run_job(session, job)

    assert job.status == "failed"
    assert "未安装转写引擎" in (job.error or "")
    assert job.completed == 0
    assert job.failed == 1
    assert not list(Path(job.output_dir, "文稿").glob("*.txt"))


def test_faster_whisper_falls_back_to_cpu_when_cuda_device_fails(monkeypatch):
    """Windows without cuBLAS raises at inference time, not load time.

    The engine must retry on CPU instead of surfacing a cublas error.
    """
    service._WHISPER_MODEL_CACHE.clear()
    service._reset_cuda_state()
    calls: list[str] = []

    class FakeSegment:
        start = 0.0
        end = 2.0
        text = "回退成功"

    class FakeModel:
        def __init__(self, size, device, compute_type):
            calls.append(device)
            if device == "cuda":
                self._device = "cuda"
            else:
                self._device = "cpu"

        def transcribe(self, media, **kwargs):
            if self._device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return [FakeSegment()], None

    fake_module = type(sys)("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.delenv("DOUYIN_EXTRACT_WHISPER_DEVICE", raising=False)
    monkeypatch.delenv("DOUYIN_EXTRACT_WHISPER_CPU_ONLY", raising=False)
    monkeypatch.setattr(service, "_cuda_usable", lambda: True)

    transcript = service._transcribe_with_faster_whisper(Path("dummy.wav"))

    assert calls == ["cuda", "cpu"]
    assert transcript.engine == "faster-whisper:small:cpu"
    assert transcript.text == "回退成功"
    service._WHISPER_MODEL_CACHE.clear()
    service._reset_cuda_state()


def test_whisper_model_is_cached_between_runs(monkeypatch):
    """A 50-work job must not reload the model 50 times."""
    service._WHISPER_MODEL_CACHE.clear()
    loads: list[str] = []

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "缓存测试"

    class FakeModel:
        def __init__(self, size, device, compute_type):
            loads.append(device)

        def transcribe(self, media, **kwargs):
            return [FakeSegment()], None

    fake_module = type(sys)("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setenv("DOUYIN_EXTRACT_WHISPER_DEVICE", "cpu")

    first = service._transcribe_with_faster_whisper(Path("dummy.wav"))
    second = service._transcribe_with_faster_whisper(Path("dummy.wav"))

    assert loads == ["cpu"], "model should be constructed only once"
    assert first.text == second.text == "缓存测试"
    service._WHISPER_MODEL_CACHE.clear()


def test_cuda_failure_disables_gpu_for_later_works(monkeypatch):
    """One missing cuBLAS must not cost minutes on every subsequent work."""
    service._WHISPER_MODEL_CACHE.clear()
    service._reset_cuda_state()
    monkeypatch.delenv("DOUYIN_EXTRACT_WHISPER_DEVICE", raising=False)
    monkeypatch.setenv("DOUYIN_EXTRACT_WHISPER_CPU_ONLY", "false")
    monkeypatch.setattr(service, "_cuda_usable", lambda: True)

    calls: list[str] = []

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "回退"

    class FakeModel:
        def __init__(self, size, device, compute_type):
            calls.append(device)
            self.device = device

        def transcribe(self, media, **kwargs):
            if self.device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found")
            return [FakeSegment()], None

    fake_module = type(sys)("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    service._transcribe_with_faster_whisper(Path("a.wav"))
    assert calls == ["cuda", "cpu"]

    monkeypatch.setattr(service, "_cuda_usable", lambda: True)
    service._transcribe_with_faster_whisper(Path("b.wav"))
    assert calls == ["cuda", "cpu"], "second work should skip the doomed GPU attempt"

    service._WHISPER_MODEL_CACHE.clear()
    service._reset_cuda_state()


def test_probe_duration_falls_back_to_ffmpeg_when_ffprobe_missing(tmp_path, monkeypatch):
    """ImageMagick-style installs ship ffmpeg only; duration must still work."""
    media = tmp_path / "clip.wav"
    media.write_bytes(b"RIFF" + b"\x00" * 2048)

    monkeypatch.setattr(service, "media_tool", lambda name: None if name == "ffprobe" else "ffmpeg")

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = (
            "Input #0, wav, from 'clip.wav':\n"
            "  Duration: 00:01:23.45, bitrate: 128 kb/s\n"
        )

    def fake_run(args, **kwargs):
        assert args[0] == "ffmpeg"
        assert "-i" in args
        return FakeResult()

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    assert service.probe_duration(media) == 83.45


def test_media_tool_honours_env_override(tmp_path, monkeypatch):
    """An explicit path keeps the app on one FFmpeg build regardless of PATH."""
    fake = tmp_path / "ffprobe-custom.exe"
    fake.write_bytes(b"stub")
    monkeypatch.setenv("DOUYIN_EXTRACT_FFPROBE", str(fake))
    monkeypatch.setattr(service.shutil, "which", lambda name: "C:/other/ffprobe.exe")

    assert service.media_tool("ffprobe") == str(fake)


def test_bad_media_marks_failed_and_keeps_partial_archive(db, tmp_path, monkeypatch):
    session, user = db
    monkeypatch.setenv("XHS_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("DOUYIN_EXTRACT_ASR_CMD", _stub_asr(tmp_path))

    manifest = json.dumps(
        {
            "works": [
                {
                    "work_id": "666666",
                    "media_url": str(tmp_path / "missing.mp4"),
                },
                {
                    "work_id": "777777",
                    "transcript": "自带内容",
                    "title": "第二条",
                },
            ]
        },
        ensure_ascii=False,
    )
    job = service.create_job(session, user, source_type="manifest", source=manifest)
    job = service.run_job(session, job)

    assert job.status == "partial"
    assert job.failed == 1
    assert job.completed == 1
    audit = Path(job.output_dir, "核对记录.md").read_text(encoding="utf-8")
    assert "失败：1" in audit
    works = {work.work_id: work for work in session.query(DouyinWork).filter_by(job_id=job.id)}
    assert works["666666"].status == "failed"
    assert "媒体" in (works["666666"].error or "")


def test_deliverables_are_atomic_files(db, tmp_path, monkeypatch):
    session, user = db
    monkeypatch.setenv("XHS_STORAGE_DIR", str(tmp_path / "storage"))
    target = tmp_path / "atomic.txt"
    service.write_text(target, "内容")
    service.write_text(target, "新内容")
    assert target.read_text(encoding="utf-8") == "新内容"
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    from backend.app.core.database import get_db

    monkeypatch.setenv("XHS_STORAGE_DIR", str(tmp_path / "storage"))
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    register = client.post(
        "/api/auth/register", json={"username": "douyin-api", "password": "secret123"}
    )
    token = register.json()["access_token"]
    yield client, {"Authorization": f"Bearer {token}"}
    app.dependency_overrides.pop(get_db, None)


def test_api_create_run_and_download(api_client, tmp_path, monkeypatch):
    client, headers = api_client
    manifest = json.dumps(
        {
            "works": [
                {
                    "work_id": "888888",
                    "title": "API 作品",
                    "transcript": "接口测试口播",
                    "srt": "1\n00:00:00,000 --> 00:00:01,000\n接口测试\n",
                }
            ]
        },
        ensure_ascii=False,
    )
    created = client.post(
        "/api/douyin/extract/jobs",
        headers=headers,
        json={"source_type": "manifest", "source": manifest, "auto_start": False},
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    listed = client.get("/api/douyin/extract/jobs", headers=headers).json()
    assert listed["total"] == 1

    run = client.post(f"/api/douyin/extract/jobs/{job_id}/run-sync", headers=headers)
    assert run.status_code == 200, run.text
    payload = run.json()
    assert payload["status"] == "completed"
    assert payload["completed"] == 1
    assert any(item["path"].endswith(".txt") for item in payload["files"])

    text_file = next(item["path"] for item in payload["files"] if item["path"].endswith(".txt"))
    downloaded = client.get(
        f"/api/douyin/extract/jobs/{job_id}/file",
        headers=headers,
        params={"path": text_file},
    )
    assert downloaded.status_code == 200
    assert "接口测试口播" in downloaded.content.decode("utf-8")

    meta = client.get("/api/douyin/extract/meta", headers=headers).json()
    assert "asr_ready" in meta and "hint" in meta


def test_api_rejects_unknown_source_type(api_client):
    client, headers = api_client
    response = client.post(
        "/api/douyin/extract/jobs",
        headers=headers,
        json={"source_type": "nope", "source": "x"},
    )
    assert response.status_code == 422
    assert "detail" in response.json()


def test_api_path_traversal_is_rejected(api_client, monkeypatch):
    client, headers = api_client
    manifest = json.dumps({"works": [{"work_id": "999999", "transcript": "内容"}]})
    created = client.post(
        "/api/douyin/extract/jobs",
        headers=headers,
        json={"source_type": "manifest", "source": manifest, "auto_start": False},
    )
    job_id = created.json()["id"]
    client.post(f"/api/douyin/extract/jobs/{job_id}/run-sync", headers=headers)
    response = client.get(
        f"/api/douyin/extract/jobs/{job_id}/file",
        headers=headers,
        params={"path": "../../../../secret.txt"},
    )
    assert response.status_code == 400
