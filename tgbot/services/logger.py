import logging
import sys

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )
    
    # Optional: set levels for other loggers
    logging.getLogger('aiogram').setLevel(logging.INFO)
    logging.getLogger('aiosqlite').setLevel(logging.WARNING)
