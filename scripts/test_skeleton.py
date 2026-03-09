import argparse
import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def split_blocks(text: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n+", text) if block.strip()]


def parse_block(block: str) -> dict | None:
    try:
        parsed = yaml.safe_load(block)
        return parsed if isinstance(parsed, dict) else None
    except yaml.YAMLError as error:
        logger.warning("Failed to parse YAML block: %s", error)
        return None


def preview_value(value, max_len: int = 120) -> str:
    text = str(value).replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def run(file_path: Path) -> None:
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    blocks = split_blocks(text)
    logger.info("Total blocks: %d", len(blocks))

    parsed_count = 0
    for index, block in enumerate(blocks, start=1):
        parsed = parse_block(block)
        if parsed is None:
            logger.info("Block %d: skipped (not a dict)", index)
            continue

        parsed_count += 1
        fields = list(parsed.keys())
        logger.info("Block %d fields: %s", index, ", ".join(fields))
        for field_name in fields:
            logger.info("  %s: %s", field_name, preview_value(parsed[field_name]))

    logger.info("Parsed dict blocks: %d/%d", parsed_count, len(blocks))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse skeleton.txt blocks as YAML and log parsed fields."
    )
    parser.add_argument(
        "file_path",
        nargs="?",
        default="data/google/adk-python/.analysis/skeleton.txt",
        help="Path to skeleton file (default: data/google/adk-python/.analysis/skeleton.txt)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level",
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    file_path = Path(args.file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    run(file_path)


if __name__ == "__main__":
    main()
