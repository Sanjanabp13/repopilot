from src.ingestion.loader import _normalize_remote_url


def test_normalize_https_github_url():
    url = "  https://github.com/KalyanM45/End-to-End-Airbnb-Price-Prediction.git/  "
    assert _normalize_remote_url(url) == "https://github.com/KalyanM45/End-to-End-Airbnb-Price-Prediction.git"


def test_normalize_ssh_github_url():
    url = "git@github.com:KalyanM45/End-to-End-Airbnb-Price-Prediction.git"
    assert _normalize_remote_url(url) == "https://github.com/KalyanM45/End-to-End-Airbnb-Price-Prediction.git"


def test_invalid_remote_url_raises():
    try:
        _normalize_remote_url("not a valid git URL")
        assert False, "Expected ValueError for malformed remote URL"
    except ValueError:
        pass
