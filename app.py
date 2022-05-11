#!/usr/bin/env python3
import os
import re

from functools import lru_cache

import urllib3

from sanic import Sanic
from sanic.log import logger
from sanic.response import json, text


http = urllib3.PoolManager()
re_heading = re.compile(r'<h2>([^<]+?)</h2>')
re_ref_body = re.compile(r'<h3>([^<(]+?) \(Gospel\)</h3>([^<]+?)<p />')

@lru_cache(maxsize=3)
def fetch(y, m, d):
    url = f"https://www.grandtier.com/nycathedral/jgetreadings.php?y={y}&m={m}&d={d}"
    raw = http.request('GET', url).data.decode('utf8')[21:-3]
    heading = ref = body = ''

    m = re_heading.search(raw)
    if m:
        heading = m.group(1).split(';')[0]

    m = re_ref_body.search(raw)
    if m:
        ref = m.group(1).replace('.', ':')
        body = m.group(2)

    return {'heading': heading, 'ref': ref, 'body': body}


app = Sanic("api-gospeldesk-org")

@app.route('/')
def root(request):
    return text('Glory to Jesus Christ!')

@app.route('/v1/<y:int>/<m:int>/<d:int>')
def day(request, y, m, d):
    return json(fetch(y, m , d))
