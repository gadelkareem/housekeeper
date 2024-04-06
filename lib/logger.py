import logging
import sys

from .config import config


class Logger(logging.Logger):
    def __init__(self, name, level=logging.INFO):
        super().__init__(name, level)
        self._configure_logging()

    def _configure_logging(self):
        if not config.log_level:
            raise ValueError("log_level config is not set.")
        log_level = config.log_level.upper()
        numeric_level = getattr(logging, log_level, None)
        if not isinstance(numeric_level, int):
            raise ValueError(
                f"Invalid log level: {log_level}, set LOG_LEVEL to one of DEBUG, INFO, WARNING, ERROR, CRITICAL")

        self.setLevel(numeric_level)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        self.addHandler(handler)
        if log_level == "DEBUG":
            self.debug("Debug mode is enabled.")

    def rename(self, name):
        self.name = name

# log = Logger("root")
