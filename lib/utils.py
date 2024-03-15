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
        if not src or not dst:
            log.error(f"Error: Invalid move: {src} to {dst}")
            return
        if '@eadir' in str.lower(src) or '@eadir' in str.lower(dst):
            log.warning(f"Skipping move: {src} to {dst}")
            return

        if os.path.exists(dst):
            dst = Utils.new_unique_file(os.path.dirname(dst), dst)

        # create missing directories
        if not os.path.exists(os.path.dirname(dst)):
            os.makedirs(os.path.dirname(dst))

        log.debug(f"Moving {src} to {dst}")
        if config.dry_run:
            log.info(f"Dry run: Would move {src} to {dst}")
            return
        try:
            if os.path.isfile(src):
                if shutil.move(src, dst):
                    log.info(f"Moved {src} to {dst}")
                    if os.path.exists(src):
                        os.remove(src)
                else:
                    log.error(f"Error moving {src} to {dst}")

                return
            if os.path.isdir(src):
                for f in os.listdir(src):
                    Utils.move(os.path.join(src, f), os.path.join(dst, f))
                if os.path.exists(src) and not os.path.exists(dst):
                    shutil.move(src, dst)
                if os.path.exists(src):
                    os.rmdir(src)

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
        log.debug(f"Creating directory: {d}")
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
        if os.path.isfile(file):
            unique_filename = os.path.basename(file)
        else:
            unique_filename = os.path.dirname(file)
        count = 1
        while os.path.exists(os.path.join(dir, unique_filename)):
            name, ext = os.path.splitext(file)
            unique_filename = f"{name}_{count}{ext}"
            count += 1
        return os.path.join(dir, unique_filename)

    @staticmethod
    def extras_dir(media_path):
        e = os.path.join(media_path, "extras")
        if not os.path.exists(e):
            os.makedirs(e)
        return e

    @staticmethod
    def trailers_dir(file_path):
        e = os.path.join(file_path, "trailers")
        if not os.path.exists(e):
            log.debug(f"Creating trailers directory: {e}")
            os.makedirs(e)
        return e

    @staticmethod
    def media_dir(file_path):
        for d in config.media_dirs.values():
            if file_path.startswith(d):
                return os.path.join(d, file_path.replace(d, "").split("/")[1])
        return None

    @staticmethod
    def delete(p):
        log.debug(f"Deleting {p}")
        if config.dry_run:
            log.debug(f"Dry run: Would delete {p}")
            return
        try:
            Utils.move(p, Utils.replace_media_path(p, config.deleted_media_dir))
        except Exception as e:
            log.error(f"Error deleting {p}. Error: " + repr(e))

    @staticmethod
    def replace_media_path(p, new_path):
        for d in config.media_dirs.values():
            if p.startswith(d):
                return p.replace(d, new_path)
        return None

    @staticmethod
    def convert_size(size_bytes):
        if size_bytes == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return "%s %s" % (s, size_name[i])
