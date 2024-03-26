import os
import re
import urllib.request as request

import xmltodict

from .logger import Logger
from .config import config


class Plex:

    def __init__(self):
        self.log = Logger(__name__)

    def watched(self):
        if not config.plex:
            self.log.warning("Plex configuration not found.")
            return []
        self.log.debug(f"Checking watched media on plex.")
        contents = request.urlopen(config.plex['watched_url']).read()
        d = xmltodict.parse(contents)
        w = []
        for m in d['rss']['channel']['item']:
            o = {}
            # regex to extract title and year from title
            match = re.match(r'(.*) \((\d{4})\)', m['title'])
            if match:
                o['title'] = match.group(1)
                o['year'] = match.group(2)
            else:
                o['title'] = m['title']
                o['year'] = None
            w.append(o)

        return w
