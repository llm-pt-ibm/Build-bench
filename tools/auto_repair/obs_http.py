import time
import requests

RETRY_STATUS = {408, 429, 500, 502, 503, 504}
RETRY_WAIT_SECONDS = (10, 30, 60)


def obs_request(method: str, url: str, **kwargs) -> requests.Response:
    """Send an OBS API request, retrying timeouts and transient server errors."""
    for wait in RETRY_WAIT_SECONDS + (None,):
        try:
            r = requests.request(method, url, **kwargs)
        except requests.exceptions.RequestException:
            if wait is None:
                raise
        else:
            if r.status_code not in RETRY_STATUS or wait is None:
                return r
        time.sleep(wait)
