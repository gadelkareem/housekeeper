import os
import pickle
import sys
from datetime import datetime, timedelta
from threading import Condition

from trakt import Trakt
from trakt.objects import Show

from .cache import cache
from .config import config
from .logger import Logger

WEEK_IN_SECONDS = 604800


class TraktClient(object):

    def __init__(self):
        self.log = Logger(__name__)
        self.recent_days = 1825  # 5 years
        if not config.trakt:
            self.log.error("Trakt configuration not found.")
            return

        self.is_authenticating = Condition()
        self.authorization = None
        # Bind trakt events
        Trakt.on("oauth.token_refreshed", self.on_token_refreshed)
        self.config_import()
        self.initialize()

        # self.trakt = trakt
        # self.trakt_auth_file = os.path.abspath(
        #     os.path.join(
        #         os.path.dirname(os.path.abspath(__file__)), "..", ".pytrakt.json"
        #     )
        # )
        #
        # self.trakt.APPLICATION_ID = config.trakt["application_id"]
        # self.trakt.core.AUTH_METHOD = trakt.core.DEVICE_AUTH
        # # trakt.core.session = factory.session
        # self.trakt.core.CONFIG_PATH = self.trakt_auth_file
        #
        # if not os.path.exists(self.trakt_auth_file):
        #     self.trakt.init(
        #         client_id=config.trakt["client_id"],
        #         client_secret=config.trakt["client_secret"],
        #         store=True,
        #     )
        # self.user = User("me")

    # def watched_movies(self):
    #     if not self.trakt:
    #         self.log.warning("Trakt configuration not found.")
    #         return []
    #     self.log.debug(f"Checking watched media on trakt.")
    #
    #     w = [{"title": o.title, "year": o.year} for o in self.user.watched_movies]
    #     return w
    #
    # def watched_series(self):
    #     if not self.trakt:
    #         self.log.warning("Trakt configuration not found.")
    #         return []
    #     self.log.debug(f"Checking watched series on trakt.")
    #     w = []
    #     for o in self.user.watched_shows:
    #         if not o.next_episode:
    #             w.append({"title": o.title, "year": o.year})
    #
    #     return w

    def auth_load(self):
        try:
            with open(os.path.join(sys.path[0], ".auth.pkl"), "rb") as f:
                auth_file = pickle.load(f)
            self.authorization = auth_file
        except:
            pass

    def authenticate(self):
        if not self.is_authenticating.acquire(blocking=False):
            self.log.debug("Authentication has already been started")
            return False

        # Request new device code
        code = Trakt["oauth/device"].code()

        self.log.info(
            'Enter the code "%s" at %s to authenticate your account'
            % (code.get("user_code"), code.get("verification_url"))
        )

        # Construct device authentication poller
        poller = (
            Trakt["oauth/device"]
            .poll(**code)
            .on("aborted", self.on_aborted)
            .on("authenticated", self.on_authenticated)
            .on("expired", self.on_expired)
            .on("poll", self.on_poll)
        )

        # Start polling for authentication token
        poller.start(daemon=False)

        # Wait for authentication to complete
        return self.is_authenticating.wait()

    def initialize(self):

        self.log.debug("Initializing Trakt")
        # Try to read auth from file
        self.auth_load()

        # If not read from file, get new auth and save to file
        if not self.authorization:
            self.authenticate()

        if not self.authorization:
            raise Exception("Authentication required")

        # Simulate expired token
        # self.authorization['expires_in'] = 0

    def config_import(self):
        self.log.debug("Initializing Trakt configuration")
        Trakt.base_url = "http://api.trakt.tv"
        Trakt.configuration.defaults.http(retry=True)
        Trakt.configuration.defaults.oauth(refresh=True)
        Trakt.configuration.defaults.client(
            id=config.trakt["client_id"], secret=config.trakt["client_secret"]
        )

    def watched_movies(self, recent_days=None):
        if not recent_days:
            recent_days = self.recent_days
        if not config.trakt:
            self.log.warning("Trakt configuration not found.")
            return []
        cache_key = f"watched_movies_{recent_days}"
        movies = cache.get(cache_key, {})
        if movies:
            self.log.debug(f"Returning {len(movies)} movies from cache")
            return movies

        with Trakt.configuration.oauth.from_response(self.authorization, refresh=True):
            # Expired token will be refreshed automatically (as `refresh=True`)
            today = datetime.now()
            recent_date = today - timedelta(days=recent_days)

            self.log.debug(
                " Trakt: Movies watched in last " + str(recent_days) + " days:"
            )
            try:
                for movie in Trakt["sync/history"].movies(
                    start_at=recent_date, pagination=True
                ):
                    movie_dict = movie.to_dict()
                    try:
                        if len(movie_dict["title"]) < 2:
                            continue
                        movies[f"{movie_dict['title']} ({movie_dict['year']})"] = movie
                        # self.log.debug("Added movie " + movie_dict["title"])
                    except KeyError:
                        self.log.error(
                            f"Movie {movie_dict['title']} ({movie_dict['year']}) - IMDB ID not found."
                        )
                        pass

            except:
                raise Exception(
                    "ERROR: Could not get data from Trakt. Maybe authentication is out of date? Try to delete .auth.pkl file and run script again."
                )

        if movies:
            cache.set(cache_key, movies, expire=WEEK_IN_SECONDS)

        self.log.debug(f"Fetched {len(movies)} movies")

        return movies

    def watched_series(self, recent_days=None):
        if not recent_days:
            recent_days = self.recent_days
        if not config.trakt:
            self.log.warning("Trakt configuration not found.")
            return []
        cache_key = f"watched_episodes_{recent_days}"
        series = cache.get(cache_key, {})
        if series:
            self.log.debug(f"Returning {len(series)} series from cache")
            return series
        with Trakt.configuration.oauth.from_response(self.authorization, refresh=True):
            # Expired token will be refreshed automatically (as `refresh=True`)
            today = datetime.now()
            recent_date = today - timedelta(days=recent_days)

            self.log.debug(
                "Trakt: Episodes watched in last " + str(recent_days) + " days:"
            )
            for episode in Trakt["sync/history"].shows(
                start_at=recent_date, pagination=True, extended="full"
            ):
                # episode_dict = episode.to_dict()
                # ep_no = episode_dict["number"]
                # season_no = episode.season.pk
                # show_tvdb = episode.show.pk[1]

                # if show_tvdb in series:
                #     # show_episodes_tvdbids[show_tvdb].append(episode_dict['ids']['tvdb'])
                #     series[show_tvdb].append([season_no, ep_no])
                # else:
                #     series[show_tvdb] = []
                #     series[show_tvdb].append([season_no, ep_no])
                show: Show = episode.show
                series.setdefault(f"{show.title} ({show.year})", []).append(episode)

                # episode_dict = episode.to_dict()
                # self.log.debug(
                #     episode.show.title
                #     + " - S"
                #     + str(episode.season.pk).zfill(2)
                #     + "E"
                #     + str(episode_dict["number"]).zfill(2)
                #     + ": "
                #     + episode_dict["title"]
                # )

        if series:
            cache.set(cache_key, series, expire=WEEK_IN_SECONDS)

        self.log.debug(f"Fetched {len(series)} series")

        return series

    def on_aborted(self):
        """Device authentication aborted.

        Triggered when device authentication was aborted (either with `DeviceOAuthPoller.stop()`
        or via the "poll" event)
        """

        self.log.debug("Authentication aborted")
        self.is_authenticating.acquire()
        self.is_authenticating.notify_all()
        self.is_authenticating.release()

    def on_authenticated(self, authorization):
        """Device authenticated.

        :param authorization: Authentication token details
        :type authorization: dict
        """

        # Acquire condition
        self.is_authenticating.acquire()

        # Store authorization for future calls
        self.authorization = authorization

        # Save authorization to file
        with open(".auth.pkl", "wb") as f:
            pickle.dump(authorization, f, pickle.HIGHEST_PROTOCOL)

        self.log.debug(
            "Authentication successful - authorization: %r" % self.authorization
        )

        # Authentication complete
        self.is_authenticating.notify_all()
        self.is_authenticating.release()

    def on_expired(self):
        """Device authentication expired."""

        self.log.debug("Authentication expired")

        # Authentication expired
        self.is_authenticating.acquire()
        self.is_authenticating.notify_all()
        self.is_authenticating.release()

    def on_poll(self, callback):
        """Device authentication poll.

        :param callback: Call with `True` to continue polling, or `False` to abort polling
        :type callback: func
        """

        # Continue polling
        callback(True)

    def on_token_refreshed(self, authorization):
        # OAuth token refreshed, store authorization for future calls
        self.authorization = authorization

        self.log.debug("Token refreshed - authorization: %r" % self.authorization)
