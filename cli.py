#!/usr/bin/env python3
"""
Housekeeping script for media libraries

Usage:
    ./cli.py scan
"""
import click
from trakt import Trakt

from cleaner import Cleaner
from lib.config import config
from lib.trakt_client import TraktClient
from lib.utils import Utils
from sorter import Sorter


Utils.lock_app()


@click.group()
@click.option("--debug/--no-debug", default=False, is_flag=True)
@click.option("--dry-run", default=False, is_flag=True)
@click.pass_context
def cli(ctx, debug=False, dry_run=False):
    """Media Manager CLI"""
    if debug:
        click.echo("Debug mode is enabled")
        config.log_level = "DEBUG"
    if dry_run:
        click.echo("Dry run is enabled")
        config.dry_run = True
    ctx.call_on_close(_on_close)


def _on_close():
    # This function will be called after every command execution
    click.echo("Closing...")


@cli.command()
def sort():
    """Sort media files."""
    Sorter(config.unsorted_media_dirs).sort()


@cli.command()
def clean():
    """Delete empty media directories and low quality media files."""
    cleaner = Cleaner(config.media_dirs.values())
    cleaner.move_pre_seeded()
    cleaner.flatten_media_dirs()
    cleaner.clean()
    cleaner = Cleaner(config.final_media_dirs)
    # cleaner.move_watched()
    cleaner.unmonitor()
    cleaner.move_trailers()
    # run only between 8am and 10am
    if 7 <= Utils.get_current_hour() <= 10:
        cleaner.merge_case_duplicates() 
        cleaner.delete_low_quality()
    cleaner.fix_jellyfin_nfo()
    
    cleaner.clean()


@cli.command()
def move():
    """Move watched media files."""
    cleaner = Cleaner(config.final_media_dirs)
    # cleaner.move_watched()


@cli.command()
def test():
    """Move watched media files."""
    """Test new functionality."""
    cleaner = Cleaner(config.final_media_dirs)
    

cli.add_command(sort)
cli.add_command(clean)
cli.add_command(move)
cli.add_command(test)

if __name__ == "__main__":
    cli()
