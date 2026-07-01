import asyncio
from types import SimpleNamespace
from typing import Optional

from multidict import CIMultiDict, istr
from yarl import URL

from aiohttp import hdrs
from aiohttp.client_reqrep import (
    CIMultiDictProxy,
    ClientRequest,
    ClientResponse,
    RequestInfo,
)
from aiohttp.helpers import TimerNoop


def raw_header(raw_headers, name: istr) -> Optional[bytes]:
    for k, v in raw_headers:
        if k == name:
            return v
    return None


def has_surrogate(url: str) -> bool:
    return any(0xDC80 <= ord(c) <= 0xDCFF for c in url)


def make_broken_redirect_response(loop, *, status=302):
    raw_location = b"https://example.com/synspr\xf8ve"
    md = CIMultiDict({hdrs.LOCATION: raw_location.decode("utf-8", "surrogateescape")})
    url = URL("https://example.com/start")
    resp = ClientResponse(
        "GET",
        url,
        writer=None,
        continue100=None,
        timer=TimerNoop(),
        request_info=RequestInfo(url, method="GET", headers=CIMultiDict()),
        traces=[],
        loop=loop,
        session=None,
        stream_writer=SimpleNamespace(output_size=0),
    )
    resp.status = status
    resp._headers = CIMultiDictProxy(md)
    resp._raw_headers = ((hdrs.LOCATION, raw_location),)
    resp._closed = False
    return resp


async def latin1_redirect_location_middleware(req, handler):
    resp = await handler(req)
    if resp.status in (301, 302, 303, 307, 308):
        raw_location = raw_header(resp.raw_headers, hdrs.LOCATION) or raw_header(
            resp.raw_headers, hdrs.URI
        )
        r_url = resp.headers.get(hdrs.LOCATION) or resp.headers.get(hdrs.URI)
        if raw_location and has_surrogate(r_url):
            r_url = raw_location.decode("latin-1")  # correct url
            md = CIMultiDict(resp.headers)  # copy proxy -> mutable dict
            md[hdrs.LOCATION] = r_url  # set new url
            resp._headers = CIMultiDictProxy(md)  # set proxy back
            resp._cache.pop(
                "headers", None
            )  # pop cache so that resp.headers is re-evaluated
    return resp


async def test_middleware():
    broken_resp = make_broken_redirect_response(asyncio.get_running_loop())
    assert "\udcf8" in broken_resp.headers[hdrs.LOCATION]
    assert "ø" not in broken_resp.headers[hdrs.LOCATION]
    print("Broken URL:", repr(broken_resp.headers[hdrs.LOCATION]))

    async def handler(req):
        return broken_resp

    req = ClientRequest("GET", URL("https://example.com/start"))
    fixed_resp = await latin1_redirect_location_middleware(req, handler)

    assert "ø" in fixed_resp.headers[hdrs.LOCATION]
    assert "\udcf8" not in fixed_resp.headers[hdrs.LOCATION]
    print("Fixed URL:", repr(fixed_resp.headers[hdrs.LOCATION]))


if __name__ == "__main__":
    asyncio.run(test_middleware())
