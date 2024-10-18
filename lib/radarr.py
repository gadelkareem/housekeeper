#!/usr/bin/env python3
import time
import traceback

import requests

from .classifier import Classifier
from .config import config
from .logger import Logger
from .threaded import Threaded


class Radarr(object):
    def __init__(self):
        self.log = Logger(__name__)
        self.radarr = config.radarr

        if not self.radarr:
            self.log.warning("Radarr configuration not found.")
            return

        self.url = self.radarr["url"]
        self.api_key = self.radarr["api_key"]
        self.classifier = Classifier(config.root_path)
        self.threaded = Threaded(30)

    # https://github.com/Herjar/radarr_sonarr_watchmon/blob/master/radarr_sonarr_watchmon.py
    def unmonitor(self, watched):
        if not watched:
            return

        # Get all movies from radarr
        response = requests.get(f"{self.url}/api/v3/movie?apikey={self.api_key}")

        if response.status_code == 401:
            raise Exception(
                " ERROR: Unauthorized request to Radarr API. Are you sure the API key is correct?"
            )

        radarr_movies = response.json()
        for _id, movie in watched.items():
            movie = movie.to_dict()
            if len(movie.get("title")) < 2:
                continue
            movie_ids = movie.get("ids")
            tmdb_id = movie_ids.get("tmdb")
            imdb_id = movie_ids.get("imdb")

            if not imdb_id and not tmdb_id:
                self.log.error(f"Error: No IMDB or TMDB ID found for {movie['title']}")
                continue
            for radarr_movie in radarr_movies:
                try:
                    if len(radarr_movie.get("title")) < 2:
                        continue
                    if not radarr_movie.get("monitored"):
                        continue
                    if imdb_id != radarr_movie.get(
                        "imdbId"
                    ) and tmdb_id != radarr_movie.get("tmdbId"):
                        if not imdb_id:
                            r = self.classifier.imdb(radarr_movie["title"])
                            if r:
                                imdb_id = r.get("imdb")
                        if not imdb_id or imdb_id != radarr_movie.get("imdbId"):
                            self.log.debug(
                                f"No IMDB ID found for Radarr movie: {radarr_movie['title']}, imdb_id: {imdb_id}:{radarr_movie.get('imdbId')}, tmdb_id: {tmdb_id}:{radarr_movie.get('tmdbId')}"
                            )
                            continue

                    self.log.debug(
                        f"Unmonitoring {radarr_movie['title']}, imdb_id: {imdb_id}:{radarr_movie.get('imdbId')}, tmdb_id: {tmdb_id}:{radarr_movie.get('tmdbId')}"
                    )
                except Exception as e:
                    self.log.error(
                        f"Error: No IMDB ID found for Radarr movie {radarr_movie['title']} {repr(e)} {traceback.format_exc()}"
                    )
                    continue

                self.threaded.run(self.unmonitor_movie, radarr_movie)
            self.threaded.wait()

    def unmonitor_movie(self, movie, retry=0):
        self.log.debug(f"Unmonitoring {movie['title']}")
        movie_json = movie

        # tag = "housekeeping_watched"
        # if tag not in movie_json["tags"]:
        #     movie_json["tags"].append(tag)

        movie_json["monitored"] = False

        request_uri = (
            self.url + "/api/v3/movie/" + str(movie["id"]) + "?apikey=" + self.api_key
        )

        r = requests.put(request_uri, json=movie_json)
        if r.status_code != 200 and r.status_code != 202:
            self.log.error("   Error " + str(r.status_code) + ": " + str(r.json()))
            if retry < 3:
                time.sleep(1)
                return self.unmonitor_movie(movie, retry + 1)
            return
        self.log.info(f"Unmonitored {movie['title']}")
