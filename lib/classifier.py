import os
import re
import time
import traceback
from datetime import datetime
from urllib.error import HTTPError

import PTN
import tmdbsimple as tmdb
from imdb import Cinemagoer

from .cache import cache
from .config import config
from .logger import Logger
from .nfo import NFO
from .utils import Utils

MAX_RETRIES = 5

cd_regex = re.compile(r".*[^a-z]+cd\d+[^\d]+.*", re.IGNORECASE)
ufc_regex = re.compile(r"^ufc.*", re.IGNORECASE)
dubbed_regex = re.compile(r".*[^a-z](dubbed|dual|multi)[^a-z]+.*", re.IGNORECASE)
threed_regex = re.compile(r".*[^a-z]3d[^a-z]+.*", re.IGNORECASE)
hdr_regex = re.compile(r".*[^a-z]+hdr[^a-z]+.*", re.IGNORECASE)
remux_regex = re.compile(r".*[^a-z]+remux[^a-z]+.*", re.IGNORECASE)
series_regex = re.compile(r"^.+?[^a-z0-9]+?S(\d+)E(\d+)?[^a-z0-9]+.*$", re.IGNORECASE)

HDR = 100
DUBBED = 90
THREED = 80
REMUX = 50
FOUR_K = 40
HD = 30
CD = 10
LOW_QUALITY = -50


class Classifier:
    info = {}

    def __init__(self, file_path):
        self.log = Logger(__name__)
        self.filepath = file_path
        self.filename = os.path.basename(file_path)
        self.filename_no_ext = os.path.splitext(self.filename)[0]
        # replace dots and underscores with spaces
        self.filename_no_ext = re.sub(r"[\._]", " ", self.filename_no_ext)
        self.extension = os.path.splitext(self.filename)[1]
        self.parent_dir = (
            os.path.dirname(file_path) if os.path.isfile(file_path) else file_path
        )
        if self.parent_dir in list(config.media_dirs.values()):
            self.parent_dir = None
        self.log.debug(f"Parent dir: {self.parent_dir}")
        self.new_filename = file_path
        self.cinemagoer = Cinemagoer()
        self.tmdb_lib = tmdb
        self.tmdb_lib.API_KEY = config.tmdb_api_key

        self.info = {
            "title": self.filename_no_ext,
            "year": None,
            "kind": "unsorted",
            "genres": set(),
            "media_dir": None,
            "new_dir": None,
            "old_path": file_path,
            "languages": {"english"},
            "hdr": False,
            "resolution": None,
            "quality": None,
            "episode": None,
            "season": None,
            "codec": None,
            "group": None,
            "excess": None,
            "container": None,
            "rank": 0,
            "dubbed": False,
            "threed": False,
            "cd": False,
            "ufc": False,
            "remux": False,
        }

    def extract_year(self, filename):
        # extract title and year from string such as "Central Intelligence (2016)" using regex
        match = re.match(r"(\d{4})", filename)
        if match and match.group(1) not in ["1080", "2160"]:
            self.log.debug(f"Extracted year: {match.groups()}")
            # self.info['title'] = match.group(1)
            self.info["year"] = match.group(1)
        # elif self.parent_dir and filename != os.path.basename(self.parent_dir):
        #     self.info['title'] = os.path.basename(self.parent_dir)
        #     return self.extract_title_year(self.info['title'])

        return self.info

    @staticmethod
    def rank_file(info):
        rank = 0
        if info["hdr"]:
            rank += HDR
        if info["dubbed"]:
            rank += DUBBED
        if info["threed"]:
            rank += THREED
        if info["remux"]:
            rank += REMUX
        if info["resolution"] == "2160p":
            rank += FOUR_K
        if info["resolution"] == "1080p":
            rank += HD
        if info["cd"]:
            rank += CD
        if (
            info["resolution"] == "720p"
            or info["resolution"] == "480p"
            or info["resolution"] == "360p"
            or info["resolution"] == "240p"
            or info["resolution"] == "144p"
            or info["resolution"] == "240p"
        ):
            rank += LOW_QUALITY

        return rank

    def set_info_from_title(self, filename):
        result = {}
        # parse the torrent name using PTN
        try:
            result = PTN.parse(filename)
        except Exception as e:
            self.log.error(f"Error parsing PTN: {e}")

        self.log.debug(f"PTN result: {result}")
        # if not result or not result.get('title', None) or self.filename_no_ext in result['title']:
        #     return self.extract_title_year(filename)
        if result.get("year", None):
            self.info["year"] = result["year"]
        if result.get("title", None):
            self.info["title"] = result["title"]
        if result.get("season", None):
            self.info["kind"] = "series"

        if not self.info["year"] and self.info["kind"] != "series":
            self.extract_year(filename)

        self.info["hdr"] = result.get("hdr", False)
        self.info["resolution"] = result.get("resolution", None)
        self.info["quality"] = result.get("quality", None)
        self.info["episode"] = result.get("episode", None)
        self.info["season"] = result.get("season", None)
        self.info["codec"] = result.get("codec", None)
        self.info["group"] = result.get("group", None)
        self.info["excess"] = result.get("excess", None)
        self.info["container"] = result.get("container", None)

        self.log.debug(f"PTN info: {self.info}")
        return self.info

    def extract_info(self, filename):
        if not self.info.get("hdr", None):
            self.info["hdr"] = hdr_regex.match(filename) is not None
        self.info["dubbed"] = dubbed_regex.match(filename) is not None
        self.info["threed"] = threed_regex.match(filename) is not None
        self.info["cd"] = cd_regex.match(filename) is not None
        self.info["ufc"] = ufc_regex.match(filename) is not None
        self.info["remux"] = remux_regex.match(filename) is not None
        self.info["rank"] = self.rank_file(self.info)

        if not self.info["season"] or not self.info["episode"]:
            match = series_regex.match(filename)
            if match:
                self.info["kind"] = "series"
                self.info["season"] = match.group(1)
                self.info["episode"] = match.group(2)

        if self.info["ufc"]:
            self.info["kind"] = "series"
            self.info["season"] = 1
            self.info["episode"] = 1
            self.info["title"] = "UFC"

    def cleanup_title(self):
        # if title has text that looks like 'S01E01' or 'S0241E0231' then split it and take the first part if not empty otherwise take the second part
        if self.info["title"]:
            match = re.match(r"^(.*?)S(\d+)E(\d+)(.*)$", self.info["title"])
            if match:
                self.info["title"] = match.group(1)
                self.info["season"] = int(match.group(2))
                self.info["episode"] = int(match.group(3))
                if not self.info["title"]:
                    self.info["title"] = match.group(4)
            self.info["title"] = self.info["title"].strip()
            # if title has the year ex: 2024 then remove it and set it as the year
            match = re.match(
                r"^(.*?)[^a-z]+?(\d{4}).*$", self.info["title"], re.IGNORECASE
            )
            if match:
                self.info["title"] = match.group(1)
                self.info["year"] = match.group(2)

    def classify(self):
        self.log.debug(f"Classifying {self.filepath}")
        self.set_info_from_title(self.filename)

        self.extract_info(self.filename)
        self.cleanup_title()

        # @todo: if media is not found, try to find it using AI API
        media = self.find_media(self.info) if not self.info["ufc"] else None

        self.log.debug(f"Media: {media}")
        if media:
            self.log.debug(f"Media: {media}")
            if media["kind"]:
                self.info["kind"] = media["kind"].lower()
            if media["year"]:
                self.info["year"] = media["year"]
            if media["title"]:
                self.info["title"] = media["title"]

            if media["genres"]:
                self.info["genres"] |= set(g.lower() for g in media["genres"])
            if media["languages"]:
                self.info["languages"] |= set(l.lower() for l in media["languages"])

        self.set_media_dir()
        self.set_new_dir()

        self.log.debug(f"Classified: {self.info}")

        return self

    def classify_move(self):
        try:
            self.classify()

            if not self.info["new_dir"]:
                # raise ValueError(f"No new dir provided. {self.info}")
                self.log.error(f"No new dir provided. {self.info}")
                return

            moved = []
            # if self.parent_dir:
            #     if self.info['new_dir'] in moved:
            #         return
            #     moved.append(self.info['new_dir'])
            #     Utils.move(self.parent_dir, self.info['new_dir'])
            # else:
            if self.info["new_path"] in moved:
                return
            moved.append(self.info["new_path"])
            Utils.move(self.filepath, self.info["new_path"])
            filename_no_ext = os.path.splitext(self.filename)[0]
            parent_dir = os.path.dirname(self.filepath)
            # copy related files to that movie
            hashes = []
            for f in os.listdir(parent_dir):
                filename_no_ext2 = os.path.splitext(f)[0]
                if filename_no_ext2 == filename_no_ext:
                    _from = os.path.join(parent_dir, f)
                    _to = os.path.join(self.info["new_dir"], f)
                    if _to in moved:
                        return
                    moved.append(_to)
                    _hash = f"{_from} -> {_to}"
                    if _hash in hashes:
                        continue
                    hashes.append(_hash)
                    self.log.info(f"Moving related file: {_from} -> {_to}")
                    Utils.move(_from, _to)

        except Exception as e:
            self.log.error(f"Error sorting {self.info}: {e}")
            traceback.print_exception(type(e), e, e.__traceback__)

    def set_new_dir(self):
        if not self.info["title"]:
            self.log.error(f"No title provided. {self.info}")
            return None

        title = (
            f"{self.info['title']} ({self.info['year']})"
            if self.info.get("year", None)
            else self.info["title"]
        )
        title = Utils.clean_path(title)

        d = os.path.join(self.info["media_dir"], title)
        Utils.make_dirs(d)
        self.log.debug(f"New dir: {d}")
        self.info["new_dir"] = d

        new_filename = Utils.clean_path(self.filename)
        self.info["new_path"] = os.path.join(d, new_filename)
        return d

    def set_media_dir(self):
        # d = config.media_dir("unsorted")
        d = config.media_dir("movies")
        if self.info["kind"] == "series":
            d = config.media_dir("series")
        elif self.info["kind"] == "movie":
            d = config.media_dir("movies")
            if "documentary" in self.info["genres"]:
                d = config.media_dir("documentaries")
            elif self.info["languages"]:
                for lang in self.info["languages"]:
                    lang_dir = config.media_dir(lang)
                    if lang_dir:
                        d = lang_dir
                        break

        self.log.debug(f"Media dir: {d}")
        self.info["media_dir"] = d
        return d

    # @cache.memoize(ignore=(0,))
    def find_media(self, info):
        if not info["title"]:
            self.log.error(f"No title provided.  {self.info}")
            return None
        title = f"{info['title']} {info['year']}" if info["year"] else info["title"]

        media = cache.get(title)
        if media:
            return media

        self.log.info(f"Searching for media: {info['old_path']}")
        # media = self.imdb(title)
        # if not media:
        media = self.tmdb(title)

        if media:
            cache.set(title, media)

        return media

    @staticmethod
    @cache.memoize()
    def tmdb_genres_list(tmdb_lib):
        return (
            tmdb_lib.Genres().movie_list()["genres"]
            + tmdb_lib.Genres().tv_list()["genres"]
        )

    def tmdb_genres(self, ids):
        genres = self.tmdb_genres_list(self.tmdb_lib)
        genres = {g["id"]: g["name"] for g in genres}
        return [genres[id] for id in ids if id in genres]

    def tmdb(self, title, retry=0):
        try:
            self.log.info(f"Searching TMDB for {title}")

            search = self.tmdb_lib.Search()
            search.multi(query=title)
            if len(search.results) > 0:
                self.log.debug(f"Found TMDB {search.results}")
                media = search.results[0]
                year = (
                    datetime.strptime(media["release_date"], "%Y-%m-%d").year
                    if "release_date" in media
                    else ""
                )
                return {
                    "title": media.get("title", None) or media.get("name", None),
                    "year": year,
                    "kind": (
                        "movie"
                        if media.get("media_type", None) == "movie"
                        else "series"
                    ),
                    "genres": self.tmdb_genres(media.get("genre_ids", [])),
                    "languages": [media.get("original_language", "en")],
                }
        except HTTPError as e:
            if e.code in [429, 503, 403] and retry < MAX_RETRIES:
                self.log.info(f"Rate limit exceeded. Retrying in {retry} seconds...")
                time.sleep(retry)
                return self.tmdb(title, retry + 1)
        except Exception as e:
            self.log.debug("Error: " + repr(e))
        return None

    def imdb(self, title, retry=0):
        info = cache.get(f"imdb:{title}")
        if info:
            return info
        try:
            self.log.debug(f"Searching IMDB for {title}")
            results = self.cinemagoer.search_movie(title, 1)
            if len(results) > 0:
                media = self.cinemagoer.get_movie(results[0].movieID)
                self.log.debug(f"Found IMDB media: {media.__dict__}")
                info = {
                    "title": media.get("title", title),
                    "year": media.get("year", None),
                    "kind": "movie" if media.get("kind", None) == "movie" else "series",
                    "genres": media.get("genres", None),
                    "languages": media.get("languages", None),
                    "imdb_id": media.get("imdbID", media.get("tmdbId", None)),
                }
                cache.set(f"imdb:{title}", info)
                return info
        except HTTPError as e:
            if e.code in [429, 503, 403, 405] and retry < MAX_RETRIES:
                self.log.info(f"Rate limit exceeded. Retrying in {retry} seconds...")
                time.sleep(retry)
                return self.tmdb(title, retry + 1)
        except Exception as e:
            self.log.error("Error: " + repr(e))
        return None

    def nfo(self):
        try:
            self.log.debug(f"Searching for NFO file related to {self.filepath}")
            nfo_path = None
            parent_dir = os.path.dirname(self.filepath)
            if Utils.is_video_file(self.filepath):
                filename_no_ext = os.path.splitext(self.filename)[0]
                nfo_path = os.path.join(parent_dir, f"{filename_no_ext}.nfo")
            if not os.path.exists(nfo_path) and self.parent_dir:
                nfo_path = os.path.join(self.parent_dir, "movie.nfo")

            if not nfo_path or not os.path.exists(nfo_path):
                # Find the first NFO file in the directory
                for filename in os.listdir(self.parent_dir):
                    if filename.endswith(".nfo"):
                        nfo_path = os.path.join(self.filepath, filename)
                        break

            self.log.debug(f"Reading NFO: {nfo_path}")
            media = NFO(nfo_path).dict()
            self.log.debug(f"Found NFO media: {media}")
            return {
                "title": media.get("title", None),
                "year": media.get("year", None),
                "kind": media.get("kind", None),
                "genres": media.get("genres", None),
            }
        except Exception as e:
            self.log.debug("Error: " + repr(e))
        return None
