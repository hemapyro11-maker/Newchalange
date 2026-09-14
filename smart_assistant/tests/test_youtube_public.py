import youtube_public as yp


class FakeYDL:
    def __init__(self, payload):
        self.payload = payload
        self.params = {}
        self.requested = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, value, download=False):
        self.requested = value
        return self.payload


def test_search_videos_normalizes_public_results(monkeypatch):
    fake = FakeYDL({"entries": [{
        "id": "abc", "title": "  A   Story  ", "url": "https://youtu.be/abc",
        "channel": "Tuty Storytime", "channel_url": "https://youtube.com/@tuty",
        "view_count": 11, "duration": 58,
    }]})
    monkeypatch.setattr(yp, "_ydl", lambda: fake)
    rows = yp.search_videos("Tuty Storytime", 5)
    assert fake.requested == "ytsearch5:Tuty Storytime"
    assert rows[0]["title"] == "A Story"
    assert rows[0]["views"] == 11


def test_channel_info_returns_recent_videos(monkeypatch):
    monkeypatch.setattr(yp, "_channel_url", lambda identifier: "https://youtube.com/@tuty")
    fake = FakeYDL({
        "channel_id": "UCtest", "channel": "Tuty Storytime",
        "channel_url": "https://youtube.com/@tuty", "description": "Kids stories",
        "channel_follower_count": 4, "playlist_count": 2,
        "entries": [{"id": "v1", "title": "Lolo", "url": "https://youtu.be/v1",
                     "view_count": 11, "duration": 58}],
    })
    monkeypatch.setattr(yp, "_ydl", lambda: fake)
    info = yp.channel_info("Tuty Storytime", 10)
    assert fake.requested.endswith("/@tuty/videos")
    assert fake.params["playlistend"] == 10
    assert info["title"] == "Tuty Storytime"
    assert info["videos"][0]["title"] == "Lolo"


def test_public_errors_are_concise(monkeypatch):
    class BrokenYDL(FakeYDL):
        def extract_info(self, value, download=False):
            raise RuntimeError("failure\nwith noisy details")

    monkeypatch.setattr(yp, "_ydl", lambda: BrokenYDL({}))
    try:
        yp.search_videos("x")
    except yp.PublicYouTubeError as exc:
        assert "failure with noisy details" in str(exc)
        assert "Traceback" not in str(exc)
    else:
        raise AssertionError("expected PublicYouTubeError")


def test_inspect_url_includes_performance_and_discovery_fields(monkeypatch):
    fake = FakeYDL({
        "id": "v1", "title": "Story", "channel": "Tuty", "view_count": 20,
        "like_count": 3, "comment_count": 2, "upload_date": "20260901",
        "categories": ["Education"], "tags": ["kids", "story"],
        "webpage_url": "https://youtu.be/v1",
    })

    class FakeYoutubeDL:
        def __init__(self, options):
            self.fake = fake

        def __enter__(self):
            return self.fake

        def __exit__(self, *args):
            return False

    import yt_dlp
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    info = yp.inspect_url("https://youtu.be/v1")
    assert info["likes"] == 3
    assert info["comments"] == 2
    assert info["upload_date"] == "20260901"
    assert info["tags"] == ["kids", "story"]
