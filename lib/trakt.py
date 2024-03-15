import os
import re
import time
from datetime import datetime
import PTN
from .cache import cache
from .logger import Logger
from .config import config
from .utils import Utils
from imdb import Cinemagoer
import tmdbsimple as tmdb
from .nfo import NFO
from urllib.error import HTTPError


class Trakt:

    def __init__(self):
        self.log = Logger(__name__)

