import os

from .classifier import Classifier
from .logger import Logger
from .config import config
import trakt
from trakt.users import User


class Trakt:

    def __init__(self):
        self.log = Logger(__name__)
        if not config.trakt:
            self.log.error("Trakt configuration not found.")
            return
        self.trakt = trakt
        self.trakt_auth_file = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..',
                '.pytrakt.json'
            )
        )

        self.trakt.APPLICATION_ID = config.trakt['application_id']
        self.trakt.core.AUTH_METHOD = trakt.core.DEVICE_AUTH
        # trakt.core.session = factory.session
        self.trakt.core.CONFIG_PATH = self.trakt_auth_file

        if not os.path.exists(self.trakt_auth_file):
            self.trakt.init(
                client_id=config.trakt['client_id'],
                client_secret=config.trakt['client_secret'],
                store=True
            )
        self.user = User("me")

    def watched_movies(self):
        if not self.trakt:
            self.log.warning("Trakt configuration not found.")
            return []
        self.log.debug(f"Checking watched media on trakt.")

        # @todo add series history self.user.watched_shows
        w = [{'title': o.title, 'year': o.year} for o in self.user.watched_movies]
        return w

    def watched_series(self):
        if not self.trakt:
            self.log.warning("Trakt configuration not found.")
            return []
        self.log.debug(f"Checking watched series on trakt.")
        w = []
        for o in self.user.watched_shows:
            if not o.next_episode:
                w.append({'title': o.title, 'year': o.year})

        return w
