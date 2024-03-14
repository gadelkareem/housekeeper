#!/usr/bin/env python3
import glob
import math
import os
import re

from .logger import Logger

import PTN
import shutil
import yaml
import xml.etree.ElementTree as ET
from .config import config
from pathvalidate import sanitize_filepath

log = Logger('utils')


class Utils:

    @staticmethod
    def debug(obj, pretty=True, stop_app=True):
        if pretty:
            print(yaml.dump(obj, default_flow_style=False))
        else:
            print(obj)
        if stop_app:
            exit()

    @staticmethod
    def move(src, dst):
        if src == dst:
            log.debug(f"Skipping move: {src} to {dst}")
            return
        if os.path.exists(dst):
            dst = Utils.new_unique_file(os.path.dirname(dst), os.path.basename(dst))

        log.debug(f"Moving {src} to {dst}")
        if config.dry_run:
            log.info(f"Dry run: Would move {src} to {dst}")
            return
        try:
            if os.path.isfile(src):
                if shutil.move(src, dst):
                    log.info(f"Moved {src} to {dst}")
                else:
                    log.error(f"Error moving {src} to {dst}")
                return
            if os.path.isdir(src):
                if not os.path.exists(dst):
                    os.makedirs(dst)
                for f in os.listdir(src):
                    Utils.move(os.path.join(src, f), os.path.join(dst, f))

        except Exception as e:
            log.error(f"Error moving {src} to {dst}. Error: " + repr(e))

    @staticmethod
    def is_big_file(file):
        return os.path.isfile(file) and os.path.getsize(file) > config.hd_media_file_size

    @staticmethod
    def is_video_file(filepath):
        return os.path.isfile(filepath) and str.lower(filepath).endswith(
            ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.mpg', '.mp2', '.mpeg', '.mpe', '.mpv', '.m2v', '.m4v', '.ts'))

    @staticmethod
    def make_dirs(d):
        if not os.path.exists(d) and not config.dry_run:
            return os.makedirs(d)

    @staticmethod
    def clean_path(s):
        s = s.strip()
        s = re.sub(r'^(\[.*?\]|www\.[^\.]+\.[^\.]+)', '', s, flags=re.IGNORECASE)

        return sanitize_filepath(s)

    @staticmethod
    def size(p, human_readable=True):
        s = 0
        if os.path.isfile(p):
            s = os.path.getsize(p)
        else:
            s = sum(os.path.getsize(f) for f in glob.iglob(glob.escape(p) + '/**', recursive=True) if os.path.isfile(f))
        return Utils.convert_size(s) if human_readable else s

    @staticmethod
    def new_unique_file(dir, file):
        unique_filename = os.path.basename(file)
        count = 1
        while os.path.exists(os.path.join(dir, unique_filename)):
            name, ext = os.path.splitext(file)
            unique_filename = f"{name}_{count}{ext}"
            count += 1
        return os.path.join(dir, unique_filename)

    @staticmethod
    def delete(p):
        log.debug(f"Deleting {p}")
        if config.dry_run:
            log.debug(f"Dry run: Would delete {p}")
            return
        try:
            Utils.move(p, config.deleted_media_dir + "/")
        except Exception as e:
            log.error(f"Error deleting {p}. Error: " + repr(e))

    def convert_size(size_bytes):
        if size_bytes == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return "%s %s" % (s, size_name[i])
