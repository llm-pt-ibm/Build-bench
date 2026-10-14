"""Failures of the build infrastructure (network, DNS) are not caused by the
package, so they are not reported to the model as failed builds: the backend
retries the build, and if the failure persists the check returns
"Build infrastructure error!", which ends the package's run without using up
the model's attempts."""
import re
import time

INFRA_ERROR = re.compile(
    r"Failed to resolve|Temporary failure in name resolution|Name or service not known"
    r"|Network is unreachable|No route to host|Connection (?:timed out|refused|reset by peer)"
    r"|Max retries exceeded with url|UnknownHostException|Unknown host:|Could not resolve host",
    re.IGNORECASE)
RETRY_WAITS = (60, 180, 300)


def infra_failure(log_text: str):
    """The first line that shows a network failure, or None."""
    m = INFRA_ERROR.search(log_text)
    if not m:
        return None
    start = log_text.rfind("\n", 0, m.start()) + 1
    end = log_text.find("\n", m.end())
    return log_text[start:end if end >= 0 else None].strip()[:300]


def retry_or_give_up(attempt: int, line: str, rebuild):
    """Wait and rebuild (returns None) or, after the last retry, the message."""
    if attempt < len(RETRY_WAITS):
        time.sleep(RETRY_WAITS[attempt])
        rebuild()
        return None
    return (f"Build infrastructure error! The build host could not reach the network ({line}); the build was "
            f"retried {len(RETRY_WAITS)} times. This failure is not caused by the package.")
