#!/usr/bin/env python3
"""
Audio Track Manager for managing default audio tracks in video files.
Scans video files and ensures English is the default audio track when available.
"""

import os
import subprocess
import json
import glob
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .logger import Logger
from .config import config
from .utils import Utils
from .threaded import Threaded


class AudioManager:
    """Manages audio tracks in video files, ensuring English is the default when available."""
    
    def __init__(self, dirs: List[str]):
        """Initialize the AudioManager with directories to scan."""
        self.dirs = dirs
        self.log = Logger(__name__)
        self.threaded = Threaded(config.max_threads if hasattr(config, 'max_threads') else 3)
        self.processed_files = []
        self.errors = []
        
    def scan_and_fix_audio_tracks(self) -> None:
        """Scan all video files and fix audio tracks where needed."""
        self.log.info(f"Starting audio track scan for {len(self.dirs)} directories...")
        
        # Collect all video files
        video_files = []
        for media_dir in self.dirs:
            if not os.path.exists(media_dir):
                self.log.warning(f"Directory does not exist: {media_dir}")
                continue
                
            self.log.debug(f"Scanning directory: {media_dir}")
            for file_path in glob.iglob(glob.escape(media_dir) + "/**", recursive=True):
                if self._should_process_file(file_path):
                    video_files.append(file_path)
        
        self.log.info(f"Found {len(video_files)} video files to process")
        
        # Process files in parallel
        for file_path in video_files:
            self.threaded.run(self._process_video_file, file_path)
        
        self.threaded.wait()
        
        # Report results
        self._report_results()
    
    def _should_process_file(self, file_path: str) -> bool:
        """Check if a file should be processed."""
        if not Utils.is_video_file(file_path):
            return False
            
        if not Utils.is_big_file(file_path):
            return False
            
        # Skip system files and directories
        if any(skip in file_path.lower() for skip in ['@eadir', 'plex', '.ds_store', 'thumbs.db']):
            return False
            
        return True
    
    def _process_video_file(self, file_path: str) -> None:
        """Process a single video file to fix audio tracks."""
        try:
            self.log.debug(f"Processing: {file_path}")
            
            # Get audio track information
            audio_tracks = self._get_audio_tracks(file_path)
            if not audio_tracks:
                self.log.debug(f"No audio tracks found: {file_path}")
                return
            
            # Find current default track and English tracks
            default_track = self._get_default_audio_track(audio_tracks)
            english_tracks = self._get_english_audio_tracks(audio_tracks)
            
            if not english_tracks:
                self.log.debug(f"No English audio tracks found: {file_path}")
                return
            
            # Check if we need to change the default track
            if default_track:
                default_lang = default_track.get('tags', {}).get('language', '').lower()
                if default_lang in ['eng', 'en', 'english']:
                    self.log.debug(f"Default track is already English: {file_path}")
                    return
            
            # Find the best English track to set as default
            best_english_track = self._select_best_english_track(english_tracks)
            if not best_english_track:
                self.log.debug(f"No suitable English track found: {file_path}")
                return
            
            # Set the English track as default
            if self._set_default_audio_track(file_path, best_english_track):
                self.processed_files.append({
                    'file': file_path,
                    'old_default': default_track,
                    'new_default': best_english_track
                })
                self.log.info(f"Fixed audio track for: {os.path.basename(file_path)}")
            
        except Exception as e:
            self.log.error(f"Error processing {file_path}: {str(e)}")
            self.errors.append({'file': file_path, 'error': str(e)})
    
    def _get_audio_tracks(self, file_path: str) -> List[Dict]:
        """Get audio track information using ffprobe."""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_streams', '-select_streams', 'a', file_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                self.log.warning(f"ffprobe failed for {file_path}: {result.stderr}")
                return []
            
            data = json.loads(result.stdout)
            return data.get('streams', [])
            
        except subprocess.TimeoutExpired:
            self.log.warning(f"ffprobe timeout for {file_path}")
            return []
        except json.JSONDecodeError:
            self.log.warning(f"Invalid JSON from ffprobe for {file_path}")
            return []
        except Exception as e:
            self.log.warning(f"Error getting audio tracks for {file_path}: {str(e)}")
            return []
    
    def _get_default_audio_track(self, audio_tracks: List[Dict]) -> Optional[Dict]:
        """Find the current default audio track."""
        for track in audio_tracks:
            if track.get('disposition', {}).get('default', 0) == 1:
                return track
        
        # If no explicit default, first track is usually default
        return audio_tracks[0] if audio_tracks else None
    
    def _get_english_audio_tracks(self, audio_tracks: List[Dict]) -> List[Dict]:
        """Find all English audio tracks."""
        english_tracks = []
        
        for track in audio_tracks:
            tags = track.get('tags', {})
            language = tags.get('language', '').lower()
            
            # Check various language indicators
            if language in ['eng', 'en', 'english']:
                english_tracks.append(track)
                continue
            
            # Check title for English indicators
            title = tags.get('title', '').lower()
            if any(indicator in title for indicator in ['english', 'eng']):
                english_tracks.append(track)
        
        return english_tracks
    
    def _select_best_english_track(self, english_tracks: List[Dict]) -> Optional[Dict]:
        """Select the best English track based on quality and preferences."""
        if not english_tracks:
            return None
        
        # Sort by codec quality and channel count
        def track_score(track):
            score = 0
            
            # Prefer higher channel count
            channels = track.get('channels', 0)
            score += channels * 10
            
            # Prefer certain codecs
            codec = track.get('codec_name', '').lower()
            if codec in ['dts', 'truehd', 'dts-hd']:
                score += 50
            elif codec in ['ac3', 'eac3']:
                score += 30
            elif codec in ['aac']:
                score += 20
            
            # Prefer higher bit rate
            bit_rate = int(track.get('bit_rate', 0))
            score += bit_rate // 1000  # Convert to kbps and add to score
            
            return score
        
        # Return the highest scoring track
        return max(english_tracks, key=track_score)
    
    def _set_default_audio_track(self, file_path: str, target_track: Dict) -> bool:
        """Set the specified track as default using mkvpropedit or ffmpeg."""
        if config.dry_run:
            self.log.info(f"Dry run: Would set track {target_track.get('index', 0)} as default in {file_path}")
            return True
        
        # Try mkvpropedit first (for MKV files)
        if file_path.lower().endswith('.mkv'):
            return self._set_default_mkv_track(file_path, target_track)
        else:
            return self._set_default_ffmpeg_track(file_path, target_track)
    
    def _set_default_mkv_track(self, file_path: str, target_track: Dict) -> bool:
        """Set default track using mkvpropedit for MKV files."""
        try:
            track_index = target_track.get('index', 0)
            
            # mkvpropedit uses 1-based indexing for tracks
            mkv_track_id = track_index + 1
            
            cmd = [
                'mkvpropedit', file_path,
                '--edit', f'track:a{mkv_track_id}',
                '--set', 'flag-default=1'
            ]
            
            # First, remove default flag from all audio tracks
            audio_tracks = self._get_audio_tracks(file_path)
            for i, track in enumerate(audio_tracks):
                if track.get('disposition', {}).get('default', 0) == 1:
                    unset_cmd = [
                        'mkvpropedit', file_path,
                        '--edit', f'track:a{i+1}',
                        '--set', 'flag-default=0'
                    ]
                    subprocess.run(unset_cmd, capture_output=True, timeout=60)
            
            # Set the new default track
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                self.log.debug(f"Successfully set default audio track using mkvpropedit: {file_path}")
                return True
            else:
                self.log.warning(f"mkvpropedit failed for {file_path}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self.log.warning(f"mkvpropedit timeout for {file_path}")
            return False
        except Exception as e:
            self.log.warning(f"Error using mkvpropedit for {file_path}: {str(e)}")
            return False
    
    def _set_default_ffmpeg_track(self, file_path: str, target_track: Dict) -> bool:
        """Set default track using ffmpeg (creates new file)."""
        try:
            # Create temporary output file
            temp_file = file_path + '.tmp'
            track_index = target_track.get('index', 0)
            
            # Build ffmpeg command to copy all streams and set default audio track
            cmd = [
                'ffmpeg', '-y', '-i', file_path,
                '-map', '0',
                '-c', 'copy',
                f'-disposition:a:{track_index}', 'default',
                temp_file
            ]
            
            # Remove default flag from other audio tracks
            audio_tracks = self._get_audio_tracks(file_path)
            for i, track in enumerate(audio_tracks):
                if i != track_index:
                    cmd.extend([f'-disposition:a:{i}', '0'])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                # Replace original file with temp file
                os.replace(temp_file, file_path)
                self.log.debug(f"Successfully set default audio track using ffmpeg: {file_path}")
                return True
            else:
                self.log.warning(f"ffmpeg failed for {file_path}: {result.stderr}")
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return False
                
        except subprocess.TimeoutExpired:
            self.log.warning(f"ffmpeg timeout for {file_path}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return False
        except Exception as e:
            self.log.warning(f"Error using ffmpeg for {file_path}: {str(e)}")
            if 'temp_file' in locals() and os.path.exists(temp_file):
                os.remove(temp_file)
            return False
    
    def _report_results(self) -> None:
        """Report the results of the audio track processing."""
        self.log.info(f"Audio track processing completed:")
        self.log.info(f"  - Files processed: {len(self.processed_files)}")
        self.log.info(f"  - Errors: {len(self.errors)}")
        
        if self.processed_files:
            self.log.info("Successfully processed files:")
            for item in self.processed_files[:10]:  # Show first 10
                self.log.info(f"  - {os.path.basename(item['file'])}")
            if len(self.processed_files) > 10:
                self.log.info(f"  ... and {len(self.processed_files) - 10} more")
        
        if self.errors:
            self.log.warning("Files with errors:")
            for item in self.errors[:5]:  # Show first 5 errors
                self.log.warning(f"  - {os.path.basename(item['file'])}: {item['error']}")
            if len(self.errors) > 5:
                self.log.warning(f"  ... and {len(self.errors) - 5} more errors") 