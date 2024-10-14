import os
from pathlib import Path
import argparse
from ..config import Configs
from rich import print

def main():
    args = parse_args()
    config_path = args.config_path
    print(Configs.from_yaml(config_path))

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