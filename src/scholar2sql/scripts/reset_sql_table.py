import os
from pathlib import Path
import argparse
import asyncio
from ..config import Configs

def main():
    args = parse_args()
    config_path = args.config_path
    configs = Configs.from_yaml(config_path)
    asyncio.run(configs.sql_database.drop_table())
    asyncio.run(configs.sql_database.create_table())
    

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