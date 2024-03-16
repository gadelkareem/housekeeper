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
    def fix_permissions_dir(self):
        return self.config['fix_permissions_dir'] if 'fix_permissions_dir' in self.config else None

    @property
    def min_file_size(self):
        return self.config['min_file_size'] if 'min_file_size' in self.config else 50000000  # 50MB

    @property
    def min_dir_size(self):
        return self.config['min_dir_size'] if 'min_dir_size' in self.config else 100000000  # 100MB

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


config = Config()
