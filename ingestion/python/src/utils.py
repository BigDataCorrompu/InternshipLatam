import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write_json(filepath: str, filename: str, data: dict) -> None:
    """Write a dictionary to a JSON file.
    
    Args:
        filepath: Directory path where the file will be written.
        filename: Name of the JSON file.
        data: Dictionary to serialize.
    """
    path = (Path(filepath) / filename).with_suffix('.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    logger.info(f"[WRITE] file={filename} status=success")

def load_json(filepath: str, filename: str) -> dict:
    """Return a dictionary from a JSON file.
    
    Args:
        filepath: Directory path where the file is located.
        filename: Name of the JSON file.
        
    Returns:
        Dictionary parsed from the JSON file.
    """
    path = (Path(filepath) / filename).with_suffix('.json')
    if not path.exists():
        logger.warning(f"[READ] file={filename} status=not_found path={path}")
        return None
    json_text = path.read_text(encoding='utf-8')
    logger.info(f"[READ] file={filename} status=success")
    return json.loads(json_text)
    
