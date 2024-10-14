import os
from pathlib import Path
import argparse
from ..config import Configs
import asyncio
import logging

logger = logging.getLogger(__name__)

def main():
    args = parse_args()
    config_path = args.config_path
    configs = Configs.from_yaml(config_path)
    asyncio.run(configs.run())

def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "config_path",
        type=str,
    )
    args = parser.parse_args()
    return args