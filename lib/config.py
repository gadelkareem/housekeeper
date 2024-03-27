import logging
import os
import yaml

ENV = os.environ.get("ENV", "nas")


class Config:
    def __init__(self):
        self.root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.config = yaml.safe_load(open(os.path.join(self.root_path, "config.yaml")))
        env_config = self.config.get(ENV, {})
        self.config.update(env_config)

    @property
    def log_level(self):
        if ("log_level" not in self.config or
                logging.getLevelName(self.config["log_level"].upper()) not in [
                    logging.DEBUG, logging.INFO,
                    logging.WARNING,
                    logging.ERROR,
                    logging.CRITICAL]):
            raise ValueError("Invalid log level. Set LOG_LEVEL to one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return self.config["log_level"].upper()

    @property
    def unsorted_media_dirs(self):
        if "unsorted_media_dirs" not in self.config:
            raise ValueError("unsorted_media_dirs config is not set.")
        for d in self.config["unsorted_media_dirs"]:
            if not os.path.exists(d):
                raise ValueError(f"Directory {d} does not exist.")
        return self.config["unsorted_media_dirs"]

    @property
    def media_dirs(self):
        if "media_dirs" not in self.config:
            raise ValueError("media_dirs config is not set.")
        for t in ["movies", "series", "documentaries", "unsorted"]:
            if t not in self.config['media_dirs']:
                raise ValueError(f"{t} directory is not set in media_dirs config.")
            self.config['media_dirs'][t] = os.path.realpath(self.config['media_dirs'][t]).rstrip("/")
            if not os.path.exists(self.config['media_dirs'][t]):
                raise ValueError(f"{t} directory {self.config['media_dirs'][t]} does not exist.")

        return self.config["media_dirs"]

    @property
    def final_media_dirs(self):
        dirs = []
        for d in self.media_dirs.values():
            if d not in self.unsorted_media_dirs:
                dirs.append(d)

        return dirs

    def media_dir(self, kind):
        return self.media_dirs[kind] if kind in self.media_dirs else None

    @property
    def hd_media_file_size(self):
        return self.config['hd_media_file_size'] if 'hd_media_file_size' in self.config else 300000000  # 300MB

    @property
    def fix_nas_permissions(self):
        return self.config['fix_nas_permissions'] if 'fix_nas_permissions' in self.config else None

    @property
    def min_file_size(self):
        return self.config['min_file_size'] if 'min_file_size' in self.config else 50000000  # 50MB

    @property
    def min_dir_size(self):
        return self.config['min_dir_size'] if 'min_dir_size' in self.config else 100000000  # 100MB

    @property
    def jellyfin_nfo_fix(self):
        j = self.config.get('jellyfin_nfo_fix', None)
        if not j:
            return None
        if 'text_replacements' not in j:
            raise ValueError("jellyfin_nfo_fix text_replacements is required.")
        return j

    @property
    def pre_seeding_dir(self):
        return self.config['pre_seeding_dir'] if 'pre_seeding_dir' in self.config else None

    @property
    def seeding_dir(self):
        return self.config['seeding_dir'] if 'seeding_dir' in self.config else None

    @property
    def tmdb_api_key(self):
        if "tmdb_api_key" not in self.config:
            raise ValueError("tmdb_api_key is not set in config.")
        return self.config["tmdb_api_key"]

    @property
    def deleted_media_dir(self):
        if "deleted_media_dir" not in self.config:
            raise ValueError("deleted_media_dir is not set in config.")
        return self.config["deleted_media_dir"]

    # add setter for log_level
    @log_level.setter
    def log_level(self, value):
        self.config["log_level"] = value

    @property
    def dry_run(self):
        if "dry_run" not in self.config:
            return False
        return self.config["dry_run"]

    @dry_run.setter
    def dry_run(self, value):
        self.config["dry_run"] = value

    @property
    def plex(self):
        t = self.config.get("plex", None)
        if not t:
            return None
        if "watched_url" not in t:
            raise ValueError("plex watched_url is required.")
        return t

    @property
    def trakt(self):
        t = self.config.get("trakt", None)
        if not t:
            return None
        if "client_id" not in t or "client_secret" not in t:
            raise ValueError("trakt client_id and client_secret are required.")
        return t

    @property
    def imdb(self):
        t = self.config.get("imdb", None)
        if not t:
            return None
        if "username" not in t or "password" not in t:
            raise ValueError("imdb username and password are required.")
        return t

    @property
    def watched_movies_media_dir(self):
        if "watched_movies_media_dir" not in self.config:
            raise ValueError("watched_movies_media_dir is not set in config.")
        return self.config["watched_movies_media_dir"]

    @property
    def watched_series_media_dir(self):
        if "watched_series_media_dir" not in self.config:
            raise ValueError("watched_series_media_dir is not set in config.")
        return self.config["watched_series_media_dir"]

config = Config()
