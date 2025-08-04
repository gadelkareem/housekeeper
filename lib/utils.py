#!/usr/bin/env python3
import logging
import fcntl
import glob
import math
import os
import re
import errno
import subprocess
from datetime import datetime

from .logger import Logger

import PTN
import shutil
import yaml
import xml.etree.ElementTree as ET
from .config import config
from pathvalidate import sanitize_filepath
from pathlib import Path
from filelock import FileLock, Timeout

class Utils:
    _log = None
    _lockfile = None

    @classmethod
    def get_logger(cls):
        if not cls._log or cls._log.level != getattr(logging, config.log_level.upper()):
            cls._log = Logger('utils')
        return cls._log

    @staticmethod
    def get_current_hour():
        return int(datetime.now().strftime('%H'))

    @classmethod
    def lock_app(cls):
        """Acquire application lock and set up signal handlers for cleanup"""
        lock_file_path = f'/tmp/housekeeper.lock'
        cls._lockfile = open(lock_file_path, 'w')

        # Set up signal handlers to ensure cleanup on termination
        import signal
        for sig in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
            signal.signal(sig, cls._signal_handler)

        try:
            # Try to grab an exclusive lock on the file, raise error otherwise
            fcntl.lockf(cls._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)

        except OSError as e:
            # if e.errno == errno.EACCES or e.errno == errno.EAGAIN:
            #     return False
            cls.get_logger().error("Another instance of the app is running. Exiting.")
            exit()

        else:
            cls.get_logger().info(f"Lock acquired {lock_file_path}")
            return True

    @staticmethod
    def debug(obj, pretty=True, stop_app=True):
        if pretty:
            print(yaml.dump(obj, default_flow_style=False))
        else:
            print(obj)
        if stop_app:
            exit()

    # fix permissions on nas
    @staticmethod
    def fix_permissions(file_path):
        file_path = file_path.replace("'", "\\'")
        return subprocess.run(["synoacltool", "-enforce-inherit", file_path])

    @classmethod
    def move(cls, src, dst):
        if src == dst:
            cls.get_logger().debug(f"Skipping move: {src} to {dst}")
            return
        if not src or not dst:
            raise ValueError(f"Error: Invalid move: {src} to {dst}")

        if '@eadir' in str.lower(src) or '@eadir' in str.lower(dst):
            cls.get_logger().warning(f"Skipping move for system files: {src} to {dst}")
            return

        if dst in config.media_dirs.values() or dst == config.deleted_media_dir:
            raise ValueError(f"Destination {dst} is a media directory. Cannot move {src} here.")

        if os.path.exists(dst) and os.path.isfile(dst):
            dst = cls.new_unique_file(os.path.dirname(dst), dst)

        # create missing directories
        if not os.path.exists(os.path.dirname(dst)):
            cls.make_dirs(os.path.dirname(dst))

        cls.get_logger().debug(f"Moving {src} to {dst}")
        if config.dry_run:
            cls.get_logger().debug(f"Dry run: Would move {src} to {dst}")
            return
        try:
            if os.path.isfile(src):
                if shutil.move(src, dst):
                    cls.get_logger().info(f"Moved {src} to {dst}")
                    if os.path.exists(src):
                        # delete file
                        shutil.rmtree(src, ignore_errors=True)
                else:
                    cls.get_logger().error(f"Error moving {src} to {dst}")
            elif os.path.isdir(src):
                for f in os.listdir(src):
                    cls.move(os.path.join(src, f), os.path.join(dst, f))
                if os.path.exists(src) and not os.path.exists(dst):
                    try:
                        shutil.move(src, dst)
                    except:
                        pass
                if os.path.exists(src):
                    shutil.rmtree(src, ignore_errors=True)

            if os.path.exists(dst):
                if config.fix_nas_permissions:
                    cls.get_logger().debug(f"Fixing permissions for {dst}")
                    cls.fix_permissions(dst)

        except Exception as e:
            cls.get_logger().error(f"Error moving {src} to {dst}. Error: " + repr(e))

    @staticmethod
    def is_big_file(file):
        return os.path.isfile(file) and os.path.getsize(file) > config.hd_media_file_size

    @staticmethod
    def is_video_file(filepath):
        return os.path.isfile(filepath) and str.lower(filepath).endswith(
            ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.mpg', '.mp2', '.mpeg', '.mpe', '.mpv', '.m2v', '.m4v', '.ts'))

    @classmethod
    def make_dirs(cls, d):
        cls.get_logger().debug(f"Creating directory: {d}")
        try:
            if not os.path.exists(d) and not config.dry_run:
                return os.makedirs(d, exist_ok=True)
        except Exception as e:
            cls.get_logger().error(f"Error creating directory: {d}", repr(e))
            return False
        return True

    @staticmethod
    def clean_path(s):
        s = s.strip()
        s = re.sub(r'^(\[.*?\]|www\.[^\.]+\.[^\.]+)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'[:\\]+', '', s, flags=re.IGNORECASE)
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
            name, ext = os.path.splitext(unique_filename)
            name = re.sub(r'[_\d]+$', '', name)
            unique_filename = f"{name}_{count}{ext}"
            count += 1

        return os.path.join(dir, unique_filename)

    @classmethod
    def extras_dir(cls, media_path):
        e = os.path.join(media_path, "extras")
        if not os.path.exists(e):
            os.makedirs(e)
        return e

    @classmethod
    def trailers_dir(cls, file_path):
        e = os.path.join(file_path, "trailers")
        if not os.path.exists(e):
            cls.get_logger().debug(f"Creating trailers directory: {e}")
            os.makedirs(e)
        return e

    @staticmethod
    def media_dir(file_path):
        for d in config.media_dirs.values():
            if file_path.startswith(d):
                return os.path.join(d, file_path.replace(d, "").split("/")[1])
        return None

    @classmethod
    def delete(cls, p):
        cls.get_logger().info(f"Deleting {p}")
        if config.dry_run:
            cls.get_logger().debug(f"Dry run: Would delete {p}")
            return
        try:
            cls.move(p, cls.replace_media_path(p, config.deleted_media_dir))
        except Exception as e:
            cls.get_logger().error(f"Error deleting {p}. Error: " + repr(e))

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

    @staticmethod
    def listdir(d):
        for f in os.scandir(d):
            if not os.path.exists(f.path):
                continue
            yield f.name

    @classmethod
    def merge_directory(cls, src_path, dst_path):
        """
        Merge contents of src_path into dst_path, keeping newer files.
        Args:
            src_path: Source directory path
            dst_path: Destination directory path
        """
        src_name = os.path.basename(src_path)
        dst_name = os.path.basename(dst_path)
        
        cls.get_logger().debug(f"Processing contents of '{src_name}' to merge into '{dst_name}'")
        
        for item in cls.listdir(src_path):
            src_item = os.path.join(src_path, item)
            dst_item = os.path.join(dst_path, item)
            
            if os.path.exists(dst_item):
                if os.path.isdir(src_item):
                    cls.get_logger().debug(f"Merging directory: {item}")
                    for sub_item in cls.listdir(src_item):
                        src_sub = os.path.join(src_item, sub_item)
                        dst_sub = os.path.join(dst_item, sub_item)
                        if not os.path.exists(dst_sub):
                            cls.get_logger().debug(f"Moving new file: {sub_item}")
                            cls.move(src_sub, dst_sub)
                        elif os.path.getmtime(src_sub) > os.path.getmtime(dst_sub):
                            cls.get_logger().debug(f"Updating newer file: {sub_item}")
                            cls.move(src_sub, dst_sub)
                else:
                    if os.path.getmtime(src_item) > os.path.getmtime(dst_item):
                        cls.get_logger().debug(f"Updating newer file: {item}")
                        cls.move(src_item, dst_item)
            else:
                cls.get_logger().debug(f"Moving new item: {item}")
                cls.move(src_item, dst_item)
        
        cls.get_logger().debug(f"Deleting source directory: {src_name}")
        cls.delete(src_path)


    @classmethod
    def get_app_lock(cls):
        """Get a filelock instance for application locking"""
        lock_file = '/tmp/housekeeper.lock'
        return FileLock(lock_file, timeout=1)  # 1 second timeout
