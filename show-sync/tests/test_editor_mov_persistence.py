"""Tests mirroring .mov persistence logic in show-sync-editor.html."""


def is_likely_filesystem_path(raw: str) -> bool:
    if not raw:
        return False
    raw = raw.strip()
    if raw.startswith("/"):
        return True
    if raw.startswith("\\\\"):
        return True
    return len(raw) > 2 and raw[1] == ":" and raw[2] in ("\\", "/")


def resolve_saved_video(last_video: str, show: dict) -> str:
    media_src = ((show.get("media") or {}).get("src") or "").strip()
    candidate = (last_video or show.get("last_video") or media_src or "").strip()
    return candidate if is_likely_filesystem_path(candidate) else ""


def save_show_last_video(show: dict) -> None:
    media = show.get("media") or {}
    src = media.get("src")
    if isinstance(src, str) and is_likely_filesystem_path(src):
        show["last_video"] = src
    else:
        show["last_video"] = ""


def test_resolve_saved_video_prefers_explicit_last_video():
    show = {"media": {"src": "/videos/other.mov"}}
    assert resolve_saved_video("/videos/a.mov", show) == "/videos/a.mov"


def test_resolve_saved_video_falls_back_to_show_last_video():
    show = {"last_video": "/videos/a.mov", "media": {"src": ""}}
    assert resolve_saved_video("", show) == "/videos/a.mov"


def test_resolve_saved_video_falls_back_to_media_src():
    show = {"media": {"src": "/videos/a.mov"}}
    assert resolve_saved_video("", show) == "/videos/a.mov"


def test_resolve_saved_video_rejects_bare_filename():
    show = {"media": {"src": "clip.mov"}}
    assert resolve_saved_video("", show) == ""


def test_resolve_saved_video_accepts_windows_path():
    show = {"media": {"src": "C:\\\\shows\\\\clip.mov"}}
    assert resolve_saved_video("", show) == "C:\\\\shows\\\\clip.mov"


def test_resolve_saved_video_accepts_windows_unc_path():
    show = {"media": {"src": "\\\\\\\\server\\\\share\\\\clip.mov"}}
    assert resolve_saved_video("", show) == "\\\\\\\\server\\\\share\\\\clip.mov"


def test_save_show_sets_last_video_from_media_src():
    show = {"media": {"src": "/videos/current.mov"}}
    save_show_last_video(show)
    assert show["last_video"] == "/videos/current.mov"


def test_save_show_does_not_set_last_video_for_blank_src():
    show = {"media": {"src": "   "}}
    save_show_last_video(show)
    assert show["last_video"] == ""


def test_save_show_does_not_set_last_video_for_bare_filename():
    show = {"media": {"src": "clip.mov"}}
    save_show_last_video(show)
    assert show["last_video"] == ""


def test_backward_compatible_when_no_video_fields():
    show = {"version": 2, "tracks": []}
    assert resolve_saved_video("", show) == ""
    save_show_last_video(show)
    assert show["last_video"] == ""
