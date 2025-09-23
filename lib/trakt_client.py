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

        # Set auth file path relative to the project root (same as config.yaml)
        # Use the same logic as config.py to ensure consistency
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.auth_file_path = os.path.join(project_root, ".auth.pkl")
        self.log.debug(f"Auth file path set to: {self.auth_file_path}")
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
        self.log.debug(f"Attempting to load auth file from: {self.auth_file_path}")
        self.log.debug(f"Auth file exists: {os.path.exists(self.auth_file_path)}")
        
        try:
            with open(self.auth_file_path, "rb") as f:
                auth_file = pickle.load(f)
            self.authorization = auth_file
            self.log.debug(f"Successfully loaded authorization from {self.auth_file_path}")
            
            # Log token info for debugging
            if self.authorization:
                created_at = self.authorization.get('created_at')
                expires_in = self.authorization.get('expires_in', 0)
                if created_at:
                    self.log.debug(f"Token created at: {datetime.fromtimestamp(created_at)}")
                    self.log.debug(f"Token expires in: {expires_in} seconds")
                    
        except FileNotFoundError:
            self.log.debug(f"Auth file not found at {self.auth_file_path}")
        except Exception as e:
            self.log.warning(f"Could not load auth file from {self.auth_file_path}: {e}")
            pass

    def auth_save(self):
        """Save current authorization to file"""
        if self.authorization:
            try:
                with open(self.auth_file_path, "wb") as f:
                    pickle.dump(self.authorization, f, pickle.HIGHEST_PROTOCOL)
                self.log.debug(f"Saved authorization to {self.auth_file_path}")
            except Exception as e:
                self.log.error(f"Failed to save authorization: {e}")

    def is_token_expired(self, buffer_minutes=30):
        """Check if token is expired or will expire within buffer_minutes"""
        if not self.authorization:
            return True
            
        expires_in = self.authorization.get('expires_in', 0)
        created_at = self.authorization.get('created_at')
        
        # If no created_at, add it based on current time (for newly created tokens)
        if not created_at and expires_in:
            created_at = datetime.now().timestamp()
            self.authorization['created_at'] = created_at
            self.auth_save()
        
        if not created_at or not expires_in:
            self.log.warning("Token missing expiry information")
            return True
            
        current_time = datetime.now().timestamp()
        expiry_time = created_at + expires_in
        buffer_time = buffer_minutes * 60
        
        # Return True if expired or will expire within buffer time
        is_expired = current_time >= (expiry_time - buffer_time)
        
        if is_expired:
            self.log.debug(f"Token expired or expiring soon. Created: {datetime.fromtimestamp(created_at)}, Expires in: {expires_in}s, Current: {datetime.fromtimestamp(current_time)}")
        else:
            remaining_hours = (expiry_time - current_time) / 3600
            self.log.debug(f"Token valid for {remaining_hours:.1f} more hours")
            
        return is_expired

    def ensure_valid_token(self):
        """Ensure we have a valid, non-expired token"""
        if not self.authorization:
            self.log.info("No authorization found, initiating authentication")
            return self.authenticate()
            
        # Check if token needs refresh (but don't force re-auth immediately)
        if self.is_token_expired(buffer_minutes=60):  # Check with 1-hour buffer
            self.log.info("Token is expired or expiring soon, attempting refresh")
            
            # Try to refresh the token using trakt.py's built-in mechanism
            try:
                # The trakt.py library should automatically refresh when we use it with refresh=True
                # Let's test if the token is still usable by making a minimal API call
                with Trakt.configuration.oauth.from_response(self.authorization, refresh=True):
                    # Make a simple API call to test and potentially refresh the token
                    try:
                        # This will trigger a refresh if needed
                        Trakt["users/settings"]()
                        self.log.info("Token successfully refreshed via API call")
                        return True
                    except Exception as api_error:
                        self.log.warning(f"API call failed, token may be invalid: {api_error}")
                        # If API call fails, fall back to re-authentication
                        raise Exception("Token refresh failed")
                        
            except Exception as refresh_error:
                self.log.warning(f"Token refresh failed: {refresh_error}")
                self.log.info("Falling back to full re-authentication")
                
                # Clear existing auth and re-authenticate
                self.authorization = None
                try:
                    os.remove(self.auth_file_path)
                    self.log.debug("Deleted expired auth file")
                except:
                    pass
                return self.authenticate()
        
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

        try:
            with Trakt.configuration.oauth.from_response(self.authorization, refresh=True):
                # Expired token will be refreshed automatically (as `refresh=True`)
                today = datetime.now()
                recent_date = today - timedelta(days=recent_days)

                self.log.debug(
                    " Trakt: Movies watched in last " + str(recent_days) + " days:"
                )
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
        except Exception as oauth_error:
            self.log.error(f"OAuth configuration failed: {oauth_error}")
            self.log.info("Token may be invalid, attempting to refresh authentication")
            # Clear the token and try to re-authenticate
            self.authorization = None
            if self.ensure_valid_token():
                # Retry the operation once with new token
                return self.watched_movies(recent_days)
            return []

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
        try:
            with Trakt.configuration.oauth.from_response(self.authorization, refresh=True):
                # Expired token will be refreshed automatically (as `refresh=True`)
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
                        show: Show = episode.show
                        id = episode.id
                        series.setdefault(f"{show.title} ({show.year})", []).append(episode)

                    page += 1
                    if episode_itr and hasattr(episode_itr, 'total_pages') and page > episode_itr.total_pages:
                        break
        except Exception as oauth_error:
            self.log.error(f"OAuth configuration failed: {oauth_error}")
            self.log.info("Token may be invalid, attempting to refresh authentication")
            # Clear the token and try to re-authenticate
            self.authorization = None
            if self.ensure_valid_token():
                # Retry the operation once with new token
                return self.watched_series(recent_days)
            return []
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

        # Add created_at timestamp for proper expiry tracking
        authorization['created_at'] = datetime.now().timestamp()
        
        # Store authorization for future calls
        self.authorization = authorization

        # Save authorization to file
        with open(self.auth_file_path, "wb") as f:
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
        # Add created_at timestamp for proper expiry tracking
        authorization['created_at'] = datetime.now().timestamp()
        self.authorization = authorization

        # Save refreshed token to file
        try:
            with open(self.auth_file_path, "wb") as f:
                pickle.dump(authorization, f, pickle.HIGHEST_PROTOCOL)
            self.log.debug(f"Saved refreshed token to {self.auth_file_path}")
        except Exception as e:
            self.log.error(f"Failed to save refreshed token: {e}")

        self.log.debug("Token refreshed - authorization: %r" % self.authorization)
