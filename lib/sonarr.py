#!/usr/bin/env python3

import requests
from trakt.objects import Show, Episode

from .config import config
from .logger import Logger
from .threaded import Threaded


class Sonarr(object):
    def __init__(self):
        self.log = Logger(__name__)
        self.sonarr = config.sonarr

        if not self.sonarr:
            self.log.warning("Sonarr configuration not found.")
            return

        self.url = self.sonarr["url"]
        self.api_key = self.sonarr["api_key"]
        self.threaded = Threaded(30)

    # https://github.com/Herjar/radarr_sonarr_watchmon/blob/master/radarr_sonarr_watchmon.py
    def unmonitor(self, series, retry=0):
        if not series:
            return
        response = requests.get(self.url + "/api/v3/series?apikey=" + self.api_key)

        if response.status_code == 401:
            self.log.error(
                "ERROR: Unauthorized request to Sonarr API. Are you sure the API key is correct?"
            )

        # Look for recently watched episodes in Sonarr and change monitored to False
        sonarr_series = response.json()
        monitored_series_count = sum(1 for show in sonarr_series if show.get("monitored"))
        total_episodes = sum(len(episodes) for episodes in series.values())
        self.log.info(f"Sonarr: Found {len(sonarr_series)} total series, {monitored_series_count} monitored")
        self.log.info(f"Trakt: Processing {len(series)} watched shows with {total_episodes} episodes for unmonitoring")
        for t, episodes in series.items():
            show: Show = episodes[0].show

            for sonarr_show in sonarr_series:
                try:
                    if not sonarr_show["monitored"]:
                        continue
                    # if "House of the Dragon" in sonarr_show["title"]:
                    #     print(f"Found {sonarr_show['title']} in Sonarr with {t}")
                    sonarr_tvdb = sonarr_show.get("tvdbId")
                    sonarr_id = sonarr_show["id"]
                    sonarr_show_title = (
                        f"{sonarr_show.get('title')} ({sonarr_show.get('year')})"
                    )
                    if (not sonarr_tvdb or show.keys[0][1] != sonarr_tvdb) and (
                        t != sonarr_show_title
                    ):
                        # Skip non-matching shows (no need to log each one)
                        continue

                except Exception as e:
                    self.log.error(
                        f"No match for {t} {e}, {show.keys[0][1]}, sonarr tvdb: {sonarr_tvdb}, sonarr title: {sonarr_show['title']}"
                    )
                    continue

                self.log.debug("Unmonitoring show " + sonarr_show_title)

                # Add tag to show
                # request_uri = (
                #     self.url
                #     + "/api/v3/series/"
                #     + str(sonarr_id)
                #     + "?apikey="
                #     + self.api_key
                # )
                # response_show = requests.get(request_uri)
                # sonarr_show_json = response_show.json()
                #
                # tag = "housekeeping_watched"
                # if tag not in sonarr_show_json["tags"]:
                #     sonarr_show_json["tags"].append(tag)
                #     r = requests.put(request_uri, json=sonarr_show_json)
                #     if r.status_code != 200 and r.status_code != 202:
                #         self.log.debug(
                #             "   Error " + str(r.status_code) + ": " + str(r.json())
                #         )

                # Get all episodes in show from Sonarr
                response_eps = requests.get(
                    self.url
                    + "/api/v3/episode/?seriesId="
                    + str(sonarr_id)
                    + "&apikey="
                    + self.api_key
                )
                sonarr_episodes = response_eps.json()
                episode: Episode
                for episode in episodes:
                    trakt_season = episode.season.pk
                    trakt_ep = episode.to_dict()["number"]

                    sonarr_ep = sonarr_season = sonarr_epid = None
                    for sonarr_episode in sonarr_episodes:
                        if not sonarr_episode["monitored"]:
                            continue
                        try:
                            sonarr_ep = sonarr_episode["episodeNumber"]
                            sonarr_season = sonarr_episode["seasonNumber"]
                            sonarr_epid = sonarr_episode["id"]

                            if trakt_season != sonarr_season or trakt_ep != sonarr_ep:
                                # Skip non-matching episodes (no need to log each one)
                                continue

                        except Exception as e:
                            self.log.error(
                                f"Error: Could not unmonitor {sonarr_show_title}, {trakt_season}x{trakt_ep} error: {repr(e)}"
                            )

                        self.threaded.run(
                            self.unmonitor_episode,
                            sonarr_show_title,
                            sonarr_season,
                            sonarr_ep,
                            sonarr_epid,
                        )

    def unmonitor_episode(
        self, sonarr_show_title, sonarr_season, sonarr_ep, sonarr_epid, retry=0
    ):
        self.log.debug(
            "Unmonitoring "
            + sonarr_show_title
            + " - S"
            + str(sonarr_season).zfill(2)
            + "E"
            + str(sonarr_ep).zfill(2)
        )

        # Get sonarr episode
        request_uri = (
            self.url + "/api/v3/episode/" + str(sonarr_epid) + "?apikey=" + self.api_key
        )
        sonarr_episode_json = requests.get(request_uri).json()

        sonarr_episode_json["monitored"] = False

        r = requests.put(request_uri, json=sonarr_episode_json)
        if r.status_code != 200 and r.status_code != 202:
            if retry < 3:
                return self.unmonitor_episode(
                    sonarr_show_title, sonarr_season, sonarr_ep, sonarr_epid, retry + 1
                )
            self.log.error(
                f"Error: Could not unmonitor {sonarr_show_title} - S{sonarr_season}E{sonarr_ep}, error: {r.json()}"
            )
        self.log.info(f"Unmonitored {sonarr_show_title} - S{sonarr_season}E{sonarr_ep}")
