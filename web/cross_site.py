"""Refuses requests that another site's page makes the browser send (cross-site request forgery).

Such a page can't read the answer, but a POST would still upload, start or rename files here.
"""
from urllib.parse import urlsplit

import config


def own_hosts(headers):
    """The host and port the request was sent to, and the one a reverse proxy says the page was opened on."""
    forwarded = (headers.get(config.FORWARDED_HOST_HEADER) or "").split(config.FORWARDED_HOST_SEPARATOR)[0]
    return {host.strip().lower() for host in (headers.get(config.HOST_HEADER) or "", forwarded) if host.strip()}


def is_cross_site(method, path, headers):
    """Whether a request that changes something, or builds the Download-all zip, came from another site's page.

    Browsers state who sent a request in Sec-Fetch-Site. Older ones are judged by where Origin, or else Referer,
    points, against the host the request was sent to. A request with none of these comes from curl or a script on
    this machine, not from a web page, and is let through.
    """
    guarded = method not in config.SAFE_METHODS or path in config.CROSS_SITE_GUARDED_PATHS
    if not guarded:
        return False
    fetch_site = headers.get(config.FETCH_SITE_HEADER)
    if fetch_site:
        return fetch_site not in config.FETCH_SITES_ALLOWED
    source = headers.get(config.ORIGIN_HEADER) or headers.get(config.REFERER_HEADER)
    if not source:
        return False
    # A sandboxed page sends Origin "null", which has no host and so never matches
    return urlsplit(source).netloc.lower() not in own_hosts(headers)
