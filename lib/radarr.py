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
        monitored_count = sum(1 for movie in radarr_movies if movie.get("monitored"))
        self.log.info(f"Radarr: Found {len(radarr_movies)} total movies, {monitored_count} monitored")
        self.log.info(f"Trakt: Processing {len(watched)} watched movies for unmonitoring")
        
        # Track movies to unmonitor
        movies_to_unmonitor = []
        
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
                            # Only log if we're having trouble with a specific movie
                            # self.log.debug(f"No match for {radarr_movie['title']}")
                            continue

                    self.log.debug(
                        f"Found match: {radarr_movie['title']}, imdb_id: {imdb_id}:{radarr_movie.get('imdbId')}, tmdb_id: {tmdb_id}:{radarr_movie.get('tmdbId')}"
                    )
                    movies_to_unmonitor.append(radarr_movie)
                except Exception as e:
                    self.log.error(
                        f"Error: No IMDB ID found for Radarr movie {radarr_movie['title']} {repr(e)} {traceback.format_exc()}"
                    )
                    continue

        # Start all unmonitoring threads
        self.log.info(f"Starting unmonitoring threads for {len(movies_to_unmonitor)} matched movies")
        for radarr_movie in movies_to_unmonitor:
            self.threaded.run(self.unmonitor_movie, radarr_movie)
        
        # Wait for all threads to complete
        self.threaded.wait()

    def unmonitor_movie(self, movie, retry=0):
        self.log.debug(f"Unmonitoring {movie['title']} (ID: {movie['id']})")
        
        request_uri = (
            self.url + "/api/v3/movie/" + str(movie["id"]) + "?apikey=" + self.api_key
        )

        # Check if it's already unmonitored
        if not movie.get("monitored", True):
            self.log.debug(f"{movie['title']} is already unmonitored, skipping")
            return

        # Try using the movie editor endpoint for bulk operations
        editor_uri = self.url + "/api/v3/movie/editor" + "?apikey=" + self.api_key
        editor_data = {
            "movieIds": [movie["id"]],
            "monitored": False
        }
        
        try:
            r = requests.put(editor_uri, json=editor_data)
            if r.status_code == 200 or r.status_code == 202:
                self.log.info(f"Unmonitored {movie['title']} via editor endpoint")
                return
            else:
                self.log.debug(f"Editor endpoint failed with {r.status_code}, trying individual movie update")
        except Exception as e:
            self.log.debug(f"Editor endpoint failed: {e}, trying individual movie update")

        # Fallback: Get the current movie data fresh from API to avoid stale data issues
        try:
            get_response = requests.get(request_uri)
            if get_response.status_code == 200:
                current_movie = get_response.json()
                current_movie["monitored"] = False
                
                # Use PUT with fresh data
                r = requests.put(request_uri, json=current_movie)
                if r.status_code == 200 or r.status_code == 202:
                    self.log.info(f"Unmonitored {movie['title']} with fresh data")
                    return
            else:
                self.log.debug(f"Could not fetch fresh movie data: {get_response.status_code}")
        except Exception as e:
            self.log.debug(f"Failed to fetch fresh movie data: {e}")
        
        # Last resort: Try with original data
        movie_json = movie.copy()
        movie_json["monitored"] = False
        
        r = requests.put(request_uri, json=movie_json)
        if r.status_code != 200 and r.status_code != 202:
            error_response = r.json()
            self.log.error(f"   Error {r.status_code} for {movie['title']} (ID: {movie['id']}): {error_response}")
            
            # Check if it's a path validation error - this indicates duplicate movies
            if any("Path" in str(err.get("propertyName", "")) and "already configured" in str(err.get("errorMessage", "")) for err in error_response):
                self.log.warning(f"Skipping {movie['title']} - appears to be a duplicate movie in Radarr database. Consider cleaning up duplicates in Radarr.")
                return
            
            # For other errors, retry
            if retry < 3:
                time.sleep(1)
                return self.unmonitor_movie(movie, retry + 1)
            return
        self.log.info(f"Unmonitored {movie['title']}")
