import glob
import logging
import os
import traceback
from datetime import datetime
import re

from lib.cache import cache
from lib.classifier import Classifier
from lib.config import config
from lib.logger import Logger
from lib.nfo import NFO
from lib.radarr import Radarr
from lib.sonarr import Sonarr
from lib.threaded import Threaded
from lib.trakt_client import TraktClient as Trakt
from lib.utils import Utils


class Cleaner:
    def __init__(self, dirs):
        self.dirs = dirs
        self.log = Logger(__name__)
        self.empty_dirs = []
        self.small_files = []
        self.threaded = Threaded(5)
        self.media = {}
        self.watched_cache = {}
        self.radarr = Radarr()
        self.sonarr = Sonarr()

    def fix_jellyfin_nfo(self):
        if not config.jellyfin_nfo_fix:
            return
        self.log.info(f"Fixing jellyfin nfo files in {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            for file in glob.iglob(glob.escape(media_dir) + "/**", recursive=True):
                if file.endswith(".nfo"):
                    n = NFO(file)
                    n.fix_jellyfin_nfo()
        self.log.info(f"Jellyfin nfo files fixed.")

    def move_trailers(self):
        self.log.info(f"Moving trailers from {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            for file in glob.iglob(glob.escape(media_dir) + "/**", recursive=True):
                filename = os.path.basename(file)
                if (
                    "trailer" in str.lower(filename)
                    and "@eadir" not in str.lower(file)
                    and Utils.is_video_file(file)
                    and "/trailers/" not in str.lower(file)
                ):
                    dst = Utils.media_dir(file)
                    trailer_dir = Utils.trailers_dir(dst)
                    self.threaded.run(
                        Utils.move, file, os.path.join(trailer_dir, filename)
                    )
        self.threaded.wait()
        self.log.info(f"Trailers moved.")

    def collect_media_info(self):
        files = []
        for d in self.dirs:
            if not os.path.exists(d):
                self.log.error(f"Directory {d} does not exist.")
                continue
            for media_dir in Utils.listdir(d):
                media_path = os.path.join(d, media_dir)

                if (
                    not media_path
                    or not os.path.exists(media_path)
                    or self.is_ignore_file(media_path, False)
                    or not os.path.isdir(media_path)
                ):
                    self.log.debug(f"Ignoring: {media_path}")
                    continue
                for filename in glob.iglob(
                    glob.escape(media_path) + "/**", recursive=True
                ):
                    p = os.path.join(media_path, filename)
                    if (
                        self.is_ignore_file(p, False)
                        or not Utils.is_video_file(p)
                        or not Utils.is_big_file(p)
                    ):
                        self.log.debug(f"Skipping: {p}")
                        continue
                    classifier = Classifier(p)
                    self.threaded.run(classifier.classify)
                    files.append(p)

        self.threaded.wait()

        for p in files:
            media_info = Classifier(p).classify().info
            if not media_info or not media_info["title"]:
                self.log.error(f"Failed to get title for: {p}")
                continue
            key = f"{media_info['title']}_{media_info['year']}_S{media_info['season']}_E{media_info['episode']}"

            if key not in self.media:
                self.media[key] = []
            self.media[key].append(media_info)

    def delete_low_quality(self):
        self.collect_media_info()


        for k, v in self.media.items():
            v = sorted(v, key=lambda x: -x["rank"])
            self.log.info(f"Ranking: {k} with {len(v)} files")
            i = 0
            for r in v:
                i += 1
                if i == 1:
                    self.log.debug(f"Keeping (Rank #{r['rank']}): {r['old_path']}")
                    new_path = (
                        os.path.dirname(os.path.dirname(r["old_path"]))
                        if ("/extras/" in r["old_path"])
                        else False
                    )
                    if new_path:
                        Utils.move(r["old_path"], new_path)
                    continue
                if i < 4:
                    self.log.debug(
                        f"Moving (Rank #{r['rank']}): {r['old_path']} to extras"
                    )
                    extras_dir = Utils.extras_dir(r["new_dir"])
                    new_path = (
                        os.path.join(extras_dir, os.path.basename(r["old_path"]))
                        if ("/extras/" not in r["old_path"])
                        else False
                    )
                    if new_path:
                        Utils.move(r["old_path"], new_path)
                    continue
                self.log.debug(f"Deleting (Rank #{r['rank']}): {r['old_path']}")
                self.threaded.run(Utils.delete, r["old_path"])
        return

    def move_pre_seeded(self):
        if not config.pre_seeding_dir and config.seeding_dir:
            self.log.info("Pre-seeding is not set.")
            return
        if os.path.exists(os.path.join(config.pre_seeding_dir, ".transferring")):
            self.log.info("Pre-seeding is in progress.")
            return

        for f in Utils.listdir(config.pre_seeding_dir):
            file_path = os.path.join(config.pre_seeding_dir, f)
            if os.path.isfile(file_path):
                self.threaded.run(
                    Utils.move, file_path, os.path.join(config.seeding_dir, f)
                )
            else:
                is_synced = True
                for f1 in Utils.listdir(file_path):
                    if f1.startswith("."):
                        is_synced = False
                        break
                if is_synced:
                    self.threaded.run(
                        Utils.move, file_path, os.path.join(config.seeding_dir, f)
                    )

    def flatten_media_dirs(self):
        self.log.info(f"Flattening {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            self.flatten_one_level(media_dir)

    def unmonitor(self):
        try:
            movies = Trakt().watched_movies()
            series = Trakt().watched_series()
            self.log.debug(f"Unmonitoring {len(movies)} movies and {len(series)} series.")
            self.radarr.unmonitor(movies)
            self.sonarr.unmonitor(series)
        except Exception as e:
            self.log.error(f"Failed to unmonitor movies or series: {e}")

    def move_watched(self):
        if not config.watched_movies_media_dir:
            self.log.error(f"Watched media directories or trakt config not set.")
            return
        self.watched_cache = self.list_watched()
        if not self.watched_cache:
            self.log.info(f"No watched media found.")
            return
        last_updated = self.watched_cache.get("last_updated")

        self.log.info(
            f"Watched cache has {len(self.watched_cache['files']['movies'])} movies and "
            f"{len(self.watched_cache['files']['series'])} series last updated: {last_updated}"
        )
        # date_last_updated = (
        #     datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S")
        #     if last_updated
        #     else None
        # )
        # if date_last_updated and (datetime.now() - date_last_updated).days < 7:
        #     return
        watched_cache = {
            "movies": [],
            "series": [],
        }
        for media_type, files in self.watched_cache["files"].items():
            for f in files:
                seen_at = (
                    datetime.strptime(f["seen_at"], "%Y-%m-%d %H:%M:%S")
                    if f.get("seen_at")
                    else None
                )
                if seen_at and (datetime.now() - seen_at).days < 7:
                    self.log.debug(f"Skipping recently watched: {f['src']}")
                    watched_cache[media_type].append(f)
                    continue
                if not os.path.exists(f["src"]):
                    self.log.debug(f"Source file does not exist: {f['src']}")
                    continue
                Utils.move(f["src"], f["dst"])

        self.watched_cache["files"] = watched_cache
        cache.set("watched_v2", self.watched_cache)

    def list_watched(self):
        cache_key = "watched_v2"
        self.watched_cache = cache.get(cache_key, {})
        if not self.watched_cache:
            self.watched_cache = {
                "files": {"movies": [], "series": []},
                "last_updated": None,
            }
        if not config.watched_movies_media_dir:
            self.log.error(f"Watched media directories or trakt config not set.")
            return
        self.log.info(f"Listing watched media.")
        watched = {
            "movies": Trakt().watched_movies(),
            "series": Trakt().watched_series(), #@TODO: fix this
        }
        if not watched["movies"] and not watched["series"]:
            self.log.info(f"No watched media found.")
            return False
        self.log.debug(f"Adding watched media on trakt.")
        try:
            watched_index = {"movies": [], "series": []}
            # move watched media to watched folder
            for k, v in watched.items():
                media_type = k
                self.log.debug(f"Checking {len(v)} {media_type}")
                for _id, media in v.items():

                    if "series" == media_type:
                        info = []
                        episode = None
                        for episode in media:
                            # info.append(
                            #     [episode.season.pk, episode.to_dict()["number"]]
                            # )
                            info.append(episode.to_dict())
                        if not episode:
                            self.log.debug(f"Could not find episode for {media}")
                            continue
                        media = episode.show
                    else:
                        # info = [media.to_dict().get("tmdbId")]
                        info = [media.to_dict()]

                    title = f"{media.title} ({media.year})"
                    title1 = media.title
                    watched_index[media_type].extend(
                        [
                            title,
                            title1,
                            Utils.clean_path(title),
                            Utils.clean_path(title1),
                        ]
                    )
                    final_path = (
                        self.find_media(title, media_type)
                        or self.find_media(title1, media_type)
                        or self.find_media(Utils.clean_path(title), media_type)
                        or self.find_media(Utils.clean_path(title1), media_type)
                    )
                    if not final_path:
                        self.log.debug(
                            f"Could not find watched media folder: {title}: {final_path} "
                        )
                        continue
                    watched_dir = (
                        config.watched_series_media_dir
                        if "series" == media_type
                        else config.watched_movies_media_dir
                    )
                    # Utils.move(final_path, os.path.join(watched_dir, Utils.clean_path(title)))

                    seen_at = media.last_watched_at or datetime.now()

                    self.watched_cache["files"][media_type].append(
                        {
                            "src": final_path,
                            "dst": os.path.join(watched_dir, Utils.clean_path(title)),
                            "seen_at": seen_at.strftime("%Y-%m-%d %H:%M:%S"),
                            "id": _id,
                            # "info": info,
                            # "title": title,
                            # "year": media.year,
                        }
                    )
            self.log.debug(
                f"Found {len(self.watched_cache['files']['movies'])} watched movies and {len(self.watched_cache['files']['series'])} series."
            )
            # move back the ones that are not in watched
            self.log.debug(f"Moving unwatched media.")
            for filename in Utils.listdir(config.watched_movies_media_dir):
                self.move_unwatched(
                    filename, watched_index["movies"], config.watched_movies_media_dir
                )
            for filename in Utils.listdir(config.watched_series_media_dir):
                self.move_unwatched(
                    filename, watched_index["series"], config.watched_series_media_dir
                )
            self.watched_cache["last_updated"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            cache.set(cache_key, self.watched_cache, expire=60 * 60 * 24)
            return self.watched_cache

        except Exception as e:
            self.log.error(f"Error moving watched: {e}")
            traceback.print_exception(type(e), e, e.__traceback__)
            return False

    def move_unwatched(self, filename, watched_index, dirpath):
        file_path = os.path.join(dirpath, filename)
        if filename not in watched_index:
            Utils.move(file_path, os.path.join(config.media_dirs["unsorted"], filename))

    def find_media(self, title, media_type):
        _final_path = False
        if len(title) < 3:
            self.log.debug(f"Title too short: {title}")
            return False
        for dir in config.final_media_dirs:
            _final_path = os.path.join(dir, title)
            if "series" == media_type and "/series/" not in _final_path:
                continue
            elif "movies" == media_type and "/series/" in _final_path:
                continue
            if os.path.exists(_final_path):
                self.log.debug(f"Found media folder for {title}: {_final_path}")
                return _final_path
        # self.log.debug(f"Could not find media folder for {title}: {_final_path}")
        return False

    def clean(self):
        self.log.info(f"Cleaning {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            for f in Utils.listdir(media_dir):
                file_path = os.path.join(media_dir, f)
                self.threaded.run(self.find_deletable_files, file_path)
                if os.path.isdir(file_path):
                    for nf in Utils.listdir(file_path):
                        self.threaded.run(
                            self.find_deletable_files, os.path.join(file_path, nf)
                        )
        self.threaded.wait()

        all_files = self.stats()

        for f in all_files:
            # Utils.delete(f['path'])
            self.threaded.run(Utils.delete, f["path"])
        self.threaded.wait()
        self.log.info(f"Cleanup Done.")

    @staticmethod
    def is_ignore_file(file_path, ignore_extras=True):
        f = str.lower(file_path)
        fn = os.path.basename(f)
        return (
            "@eadir" in f
            or "plex" in f
            or "trailer" in f
            or "/subs" in f
            or (ignore_extras and "/extras" in f)
            or str.endswith(f, ".subs")
            or
            # str.startswith(fn, '.') or
            str.endswith(f, ".meta")
            or str.endswith(f, ".nfo")
            or str.startswith(fn, ".smbdelete")
        )

    @staticmethod
    def is_ignore_flattening(file_path):
        f = str.lower(file_path)
        return any(
            substring in f
            for substring in ["@eadir", "plex", "trailer", "/subs", "/extras"]
        )  #

    @staticmethod
    def is_deletable_dir(file_path):
        f = str.lower(file_path)
        return not any(
            substring in f
            for substring in [
                "@eadir",
                "plex",
                "trailer",
                "/subs",
                "/season",
                "/extras",
            ]
        )  #

    @staticmethod
    def is_deletable_file(file_path):
        f = str.lower(file_path)
        return not f.endswith((".jpg", ".jpeg", ".png", ".nfo", ".srt", ".sub"))

    def find_deletable_files(self, file_path):
        if not os.path.exists(file_path):
            self.log.debug(f"Ignoring: {file_path}")
            return
        if os.path.isdir(file_path) and self.is_deletable_dir(file_path):
            size = Utils.size(file_path, False)
            if size < config.min_dir_size:
                self.log.debug(
                    f"Found empty dir size[{Utils.convert_size(size)}]: {file_path}"
                )
                self.empty_dirs.append({"path": file_path, "size": size})
        if (
            os.path.isfile(file_path)
            and self.is_deletable_file(file_path)
            and self.is_deletable_dir(file_path)
        ):
            size = Utils.size(file_path, False)
            if size < config.min_file_size:
                self.log.debug(
                    f"Found small file size[{Utils.convert_size(size)}]: {file_path}"
                )
                self.small_files.append({"path": file_path, "size": size})

    def stats(self):
        # sort by size
        self.empty_dirs.sort(key=lambda x: x["size"])
        self.small_files.sort(key=lambda x: x["size"])
        all_files = self.empty_dirs + self.small_files
        total_size = 0
        self.log.info(f"Biggest files:")
        for f in all_files[-10:]:
            if self.log.level <= logging.INFO:
                print(f"    - {Utils.convert_size(f['size'])} - {f['path']}")
            total_size += f["size"]

        self.log.info(f"Small Files: {len(self.small_files)}")
        self.log.info(f"Empty dirs: {len(self.empty_dirs)}")
        self.log.info(f"Total size: {Utils.convert_size(total_size)}")

        return all_files

    def flatten_one_level(self, media_dir):
        for rootdir in Utils.listdir(media_dir):
            rootdir_path = os.path.join(media_dir, rootdir)

            if not os.path.isdir(rootdir_path) or rootdir_path == media_dir:
                continue

            for file in glob.iglob(glob.escape(rootdir_path) + "/**", recursive=True):
                if self.is_ignore_flattening(file) or "/season" in str.lower(file):
                    continue

                if os.path.isdir(file) or file == os.path.join(
                    rootdir_path, os.path.basename(file)
                ):
                    continue

                self.log.debug(f"Found nested file: {file} under {rootdir_path}")
                # Making sure the new filename is unique in case of duplicates
                destination = os.path.join(rootdir_path, os.path.basename(file))
                if os.path.exists(destination):
                    destination = Utils.new_unique_file(rootdir_path, file)

                self.threaded.run(Utils.move, file, destination)
        self.threaded.wait()
        return

    def merge_case_duplicates(self):
        """
        Merge folders that have the same name with different cases.
        Keeps the version with uppercase letters in the name and prefers versions with years.
        """
        for media_dir in self.dirs:
            if not os.path.exists(media_dir):
                continue
            
            # Get all directories in the media directory using Utils.listdir
            all_dirs = [d for d in Utils.listdir(media_dir) if os.path.isdir(os.path.join(media_dir, d))]
            
            self.log.info(f"Found {len(all_dirs)} directories in {media_dir}")
            
            # Group directories by their normalized name
            case_groups = {}
            for dir_name in all_dirs:
                # Normalize the name
                normalized_name = dir_name.lower()
                # Remove year in parentheses for grouping
                normalized_name = re.sub(r'\(\d{4}\)', '', normalized_name)
                # Keep only alphanumeric chars
                normalized_name = ''.join(c for c in normalized_name if c.isalnum())
                normalized_name = normalized_name.strip()
                
                if normalized_name not in case_groups:
                    case_groups[normalized_name] = []
                case_groups[normalized_name].append(dir_name)
            
            # Process groups that have multiple variations
            duplicates_found = False
            for normalized_name, variations in case_groups.items():
                if len(variations) > 1:
                    duplicates_found = True
                    self.log.info(f"Found duplicate group: {variations}")
                    
                    # Score function to prefer versions with years and uppercase letters
                    def score_name(name):
                        score = 0
                        # Heavily prefer names with years
                        if re.search(r'\(\d{4}\)', name):
                            score += 1000
                        # Add points for uppercase letters
                        score += sum(1 for c in name if c.isupper())
                        return score
                    
                    target_dir = max(variations, key=score_name)
                    
                    for dir_name in variations:
                        if dir_name != target_dir:
                            src_path = os.path.join(media_dir, dir_name)
                            dst_path = os.path.join(media_dir, target_dir)
                            
                            self.log.info(f"Merging '{dir_name}' into '{target_dir}'")
                            self.threaded.run(Utils.merge_directory, src_path, dst_path)
            
            if not duplicates_found:
                self.log.info("No duplicates found")
            
            self.threaded.wait()
