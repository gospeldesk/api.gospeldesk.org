#!/usr/bin/env python3
import asyncio
import datetime
import sentry_sdk
import os

from collections import deque as Deque

import aiohttp
from async_lru import alru_cache

from sanic import Sanic
from sanic.exceptions import InvalidUsage
from sanic.response import json, text


SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )


app = Sanic("api-gospeldesk-org")


class BadHeadings(RuntimeError):
    pass


# Heavy lifting
# =============

# Work around https://github.com/brianglass/orthocal-python/issues/54.
OVERRIDES = {
    -76: 'Monday after Zacchaeus Sunday',
    -75: 'Tuesday after Zacchaeus Sunday',
    -74: 'Wedneseday after Zacchaeus Sunday',
    -73: 'Thursday after Zacchaeus Sunday',
    -72: 'Friday after Zacchaeus Sunday',
    -71: 'Saturday after Zacchaeus Sunday',

    -69: 'Monday before Great Lent',
    -68: 'Tuesday before Great Lent',
    -67: 'Wedneseday before Great Lent',
    -66: 'Thursday before Great Lent',
    -65: 'Friday before Great Lent',
    -64: 'Saturday before Great Lent',
}


@alru_cache(maxsize=3)
async def fetch(y, m, d):
    # validation - do this in here vs. above so that failure result is cached
    datetime.datetime.strptime(f"{y}-{m}-{d}", "%Y-%m-%d")  # will raise ValueError

    url = f"https://orthocal.info/api/gregorian/{y}/{m}/{d}/"
    print(url)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            day = await response.json()

    try:
        gospel = [r for r in day["readings"] if r["source"] == "Gospel"][0]
    except IndexError:
        heading = ""
        body = "There is no Gospel reading for today."
        ref = ""
    else:
        heading = OVERRIDES.get(day["pdist"], day["titles"][0])
        body = ""
        ref = gospel["display"].replace(".", ":")

        for i, verse in enumerate(gospel["passage"]):
            if i > 0:
                body += "\n\n" if verse["paragraph_start"] else " "
            body += verse["content"]

    return {"heading": heading, "ref": ref, "body": body}


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


@app.route("/v1/")
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
