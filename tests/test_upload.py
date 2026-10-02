from fyt import pipeline, youtube
from fyt.config import Config
from fyt.store import Job, Topics


def _setup(tmp_path, monkeypatch):
    cfg = Config(jobs_dir=str(tmp_path), require_review=False)
    Topics(cfg).add(["A topic"])

    def make_video(cfg, topic):
        job = Job.create(cfg, topic)
        job.update(status="approved")
        return job

    monkeypatch.setattr(pipeline, "make_video", make_video)
    return cfg


def test_run_skips_upload_without_token(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(youtube, "authorised", lambda: False)
    monkeypatch.setattr(pipeline, "upload_job", lambda cfg, job: (_ for _ in ()).throw(AssertionError("uploaded")))
    [job] = pipeline.run_queue(cfg, 1)
    assert job.meta["status"] == "ready"


def test_run_keeps_video_when_upload_fails(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(youtube, "authorised", lambda: True)

    def boom(cfg, job):
        raise RuntimeError("quota exceeded")

    monkeypatch.setattr(pipeline, "upload_job", boom)
    [job] = pipeline.run_queue(cfg, 1)
    assert job.meta["status"] == "upload_failed"
    assert "quota" in job.meta["upload_error"]
