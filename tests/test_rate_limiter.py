from src.services.rate_limiter import RateLimiter


def test_rate_limiter_tracks_clients_independently():
    limiter = RateLimiter(max_requests=1, window_seconds=60)

    assert limiter.allow("client-a")
    assert not limiter.allow("client-a")
    assert limiter.allow("client-b")


def test_rate_limiter_expires_requests():
    limiter = RateLimiter(max_requests=1, window_seconds=0)

    assert limiter.allow("client-a")
    assert limiter.allow("client-a")
