#!/usr/bin/env python3
import asyncio
import datetime
import re
import sentry_sdk

from collections import deque as Deque

import aiohttp
from async_lru import alru_cache

from sanic import Sanic
from sanic.exceptions import InvalidUsage
from sanic.response import json, text


sentry_sdk.init(
    dsn="https://9b2d4d4faecb8a73987e7e01c9b3f2de@o4506623256100864.ingest.sentry.io/4506623288737792",
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
)


app = Sanic("api-gospeldesk-org")


class BadHeadings(RuntimeError):
    pass


# Heavy lifting
# =============

re_headings = re.compile(r"<h2>([^<]+?)</h2>")
re_ref_body = re.compile(r"<h3>([^<(]+?) \(Gospel\)</h3>([^<]+?)<p />")
re_special = re.compile(r"<h3>([^<(]+?) \(Gospel—([^)&]+)\)</h3>([^<]+?)<p />")


@alru_cache(maxsize=3)
async def fetch(y, m, d):
    # validation - do this in here vs. above so that failure result is cached
    # if (len(y), len(m), len(d)) != (4,2,2): - TODO - app sends 2022/5/17
    #    raise ValueError
    datetime.datetime.strptime(f"{y}-{m}-{d}", "%Y-%m-%d")  # raises ValueError

    url = f"https://www.grandtier.com/nycathedral/jgetreadings.php?y={y}&m={m}&d={d}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()

    raw = html[21:-3]
    raw = raw.replace("&mdash;", "—").replace("&ndash;", "–")
    heading = ref = body = ""

    m = re_headings.search(raw)
    if not m:
        raise BadHeadings
    headings = m.group(1).split(";")

    m = re_ref_body.search(raw)
    if m:
        heading = headings[0]
        ref = m.group(1).replace(".", ":")
        body = m.group(2)
    else:
        # A feast day such as Christmas.
        m = re_special.search(raw)
        if m:
            try:
                heading = headings[1]
            except IndexError:
                heading = m.group(2)
            ref = m.group(1).replace(".", ":")
            body = m.group(3)

    return {
        "heading": heading.strip(),
        "ref": ref,
        "body": body or "Could not find a Gospel reading for today(!).",
    }


# Analytics
# =========

analytics_queue = Deque()
backoff_power = 0


async def record(url):
    async with aiohttp.ClientSession() as session:
        await session.post(
            "https://plausible.io/api/event",
            json={"name": "pageview", "url": url, "domain": "api.gospeldesk.org"},
        )


async def analytics_recorder(app):
    global backoff_power
    while 1:
        try:
            url = analytics_queue.popleft()
        except IndexError:
            await asyncio.sleep(2**backoff_power)
            backoff_power = min(backoff_power + 1, 6)  # max 64 seconds
        else:
            await record(url)
            backoff_power = max(backoff_power - 1, 1)  # min 2 seconds


app.add_task(analytics_recorder)


# Routes
# ======


@app.route("/")
def root(request):
    return text("Glory to Jesus Christ!")


@app.route("/v1/stats")
def stats(request):
    return json(
        {
            "day_cache": fetch.cache_info()._asdict(),
            "analytics_queue": {
                "n": len(analytics_queue),
                "sleep": 2**backoff_power,
            },
        }
    )


@app.route("/v1/<y>/<m>/<d>")
async def day(request, y, m, d):
    analytics_queue.append(request.url)
    try:
        return json(await fetch(y, m, d))
    except ValueError:
        raise InvalidUsage("bad date, use yyyy/mm/dd")
