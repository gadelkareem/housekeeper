#!/usr/bin/env python3
"""
Housekeeping script for media libraries

Usage:
    ./cli.py scan
"""
import os
import click
from lib.config import config
from sorter import Sorter
from cleaner import Cleaner


@click.group()
@click.option('--debug/--no-debug', default=False, is_flag=True)
@click.option('--dry-run', default=False, is_flag=True)
def cli(debug=False, dry_run=False):
    """Media Manager CLI"""
    if debug:
        click.echo('Debug mode is enabled')
        config.log_level = "DEBUG"
    if dry_run:
        click.echo('Dry run is enabled')
        config.dry_run = True


@cli.command()
def sort():
    """Sort media files."""
    Sorter(config.unsorted_media_dirs).sort()


@cli.command()
def clean():
    """Delete empty media directories and low quality media files."""
    cleaner = Cleaner(config.unsorted_media_dirs)
    # cleaner.clean()
    Cleaner(config.final_media_dirs).delete_low_quality()


cli.add_command(sort)
cli.add_command(clean)

if __name__ == '__main__':
    cli()
