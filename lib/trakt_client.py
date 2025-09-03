import os
import pickle
import sys
from datetime import datetime, timedelta
from threading import Condition

# https://github.com/fuzeman/trakt.py
from trakt import Trakt
from trakt.objects import Show, Episode

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
            self.log.debug("Loaded authorization from .auth.pkl")
        except Exception as e:
            self.log.debug(f"Could not load auth file: {e}")
            pass

    def is_token_expired(self, buffer_minutes=30):
        """Check if token is expired or will expire within buffer_minutes"""
        if not self.authorization:
            return True
            
        expires_in = self.authorization.get('expires_in', 0)
        created_at = self.authorization.get('created_at', 0)
        
        if not created_at or not expires_in:
            self.log.warning("Token missing expiry information")
            return True
            
        current_time = datetime.now().timestamp()
        expiry_time = created_at + expires_in
        buffer_time = buffer_minutes * 60
        
        # Return True if expired or will expire within buffer time
        return current_time >= (expiry_time - buffer_time)

    def ensure_valid_token(self):
        """Ensure we have a valid, non-expired token"""
        if self.is_token_expired():
            self.log.info("Token is expired or missing, initiating re-authentication")
            # Clear existing auth
            self.authorization = None
            # Delete old auth file
            try:
                os.remove(os.path.join(sys.path[0], ".auth.pkl"))
                self.log.debug("Deleted expired auth file")
            except:
                pass
            # Re-authenticate
            return self.authenticate()
        else:
            expires_in = self.authorization.get('expires_in', 0)
            created_at = self.authorization.get('created_at', 0)
            if created_at and expires_in:
                expiry_time = created_at + expires_in
                remaining_hours = (expiry_time - datetime.now().timestamp()) / 3600
                self.log.debug(f"Token valid for {remaining_hours:.1f} more hours")
            return True

    def authenticate(self):
        if not self.is_authenticating.acquire(blocking=False):
            self.log.debug("Authentication has already been started")
            return False


        print(Trakt["oauth/device"])
        # Request new device code
        code = Trakt["oauth/device"].code()
        print(code)

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

        # Ensure we have a valid token (will auto-renew if needed)
        if not self.ensure_valid_token():
            raise Exception("Authentication failed")

        # Simulate expired token
        # self.authorization['expires_in'] = 0

    def config_import(self):
        self.log.debug("Initializing Trakt configuration")
        Trakt.base_url = "https://api.trakt.tv"
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
        
        # Ensure we have a valid token before making API calls
        if not self.ensure_valid_token():
            self.log.error("Failed to obtain valid authentication token")
            return []
        cache_key = f"watched_movies_{recent_days}"
        movies = cache.get(cache_key, {})
        if movies:
            self.log.debug(f"Trakt: Returning {len(movies)} movies from cache")
            return movies

        with Trakt.configuration.oauth.from_response(self.authorization, refresh=True):
            # Expired token will be refreshed automatically (as `refresh=True`)
            today = datetime.now()
            recent_date = today - timedelta(days=recent_days)

            self.log.debug(
                " Trakt: Movies watched in last " + str(recent_days) + " days:"
            )
            try:
                page = 1
                id = None
                while True:
                    movies_itr = Trakt["sync/history"].movies(
                        start_at=recent_date, pagination=True, extended="full", per_page=10000, page=page, id=id
                    )
                    if not movies_itr:
                        self.log.error("Trakt: No movies found")
                        break
                    if not hasattr(movies_itr, 'total_pages'):
                        self.log.warning("Trakt: Invalid response from API - no total_pages attribute for movies")
                        break
                    for movie in movies_itr:
                        id = movie.id
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
                    self.log.debug(f"Fetched from Trakt, {len(movies)} movies so far.")
                    page += 1
                    if movies_itr and hasattr(movies_itr, 'total_pages') and page > movies_itr.total_pages:
                        break

            except Exception as e:
                self.log.exception(
                    "ERROR: Could not get data from Trakt. Maybe authentication is out of date? Try to delete .auth.pkl file and run script again.",
                    e,
                    exc_info=True,
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
        
        # Ensure we have a valid token before making API calls
        if not self.ensure_valid_token():
            self.log.error("Failed to obtain valid authentication token")
            return []
        cache_key = f"watched_episodes_{recent_days}"
        series = cache.get(cache_key, {})
        if series:
            self.log.debug(f"Returning {len(series)} series from cache")
            return series
        with Trakt.configuration.oauth.from_response(self.authorization, refresh=True):
            # Expired token will be refreshed automatically (as `refresh=True`)
            # Check if token is expired and log it
            if self.authorization:
                expires_in = self.authorization.get('expires_in', 0)
                created_at = self.authorization.get('created_at', 0)
                current_time = datetime.now().timestamp()
                if created_at and expires_in:
                    expiry_time = created_at + expires_in
                    if current_time > expiry_time:
                        self.log.warning(f"Trakt: Token appears expired (created: {datetime.fromtimestamp(created_at)}, expires in: {expires_in}s)")
                    else:
                        self.log.debug(f"Trakt: Token valid (expires: {datetime.fromtimestamp(expiry_time)})")
                else:
                    self.log.warning("Trakt: Token expiry information not available")
            
            today = datetime.now()
            recent_date = today - timedelta(days=recent_days)

            self.log.debug(
                "Trakt: Episodes watched in last " + str(recent_days) + " days:"
            )
            
            # Authentication should be valid at this point due to ensure_valid_token() check
            self.log.debug("Trakt: Proceeding with authenticated API calls")
            
            page = 1
            id = None
            while True:
                episode_itr = None
                try:
                    self.log.debug(f"Trakt: Requesting shows history - page {page}, start_date: {recent_date}")
                    episode_itr = Trakt["sync/history"].shows(
                        start_at=recent_date, pagination=True, extended="full", per_page=10000, page=page, id=id
                    )
                    self.log.debug(f"Trakt: API response type: {type(episode_itr)}, response: {episode_itr}")
                    
                    if episode_itr and hasattr(episode_itr, 'total_pages'):
                        self.log.debug(f"Trakt: Shows Page {page} of {episode_itr.total_pages}, items count: {len(list(episode_itr)) if hasattr(episode_itr, '__len__') else 'unknown'}")
                    elif episode_itr:
                        self.log.warning(f"Trakt: Response received but no total_pages attribute. Response type: {type(episode_itr)}, attributes: {dir(episode_itr)}")
                    else:
                        self.log.warning("Trakt: API returned None response")

                except Exception as e:
                    self.log.error(
                        f"ERROR: Could not get episodes from Trakt. Error: {e}"
                    )
                    episode_itr = None
                if not episode_itr:
                    self.log.error("Trakt: No episodes found - this might be due to expired authentication")
                    self.log.error("Trakt: Try deleting .auth.pkl file and re-running to re-authenticate")
                    break
                episode: Episode
                for episode in episode_itr:
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
                    id = episode.id
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
                page += 1
                if episode_itr and hasattr(episode_itr, 'total_pages') and page > episode_itr.total_pages:
                    break
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
        with open(os.path.join(sys.path[0], ".auth.pkl"), "wb") as f:
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

        # Save refreshed token to file
        try:
            with open(os.path.join(sys.path[0], ".auth.pkl"), "wb") as f:
                pickle.dump(authorization, f, pickle.HIGHEST_PROTOCOL)
            self.log.debug("Saved refreshed token to .auth.pkl")
        except Exception as e:
            self.log.error(f"Failed to save refreshed token: {e}")

        self.log.debug("Token refreshed - authorization: %r" % self.authorization)
