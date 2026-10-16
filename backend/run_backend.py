import argparse
import logging
import os
from pathlib import Path
import secrets
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=17321)
    parser.add_argument('--token', default=os.environ.get('AQACOPILOT_TOKEN'))
    default_data = Path(sys.executable).resolve().parent / 'data' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1] / 'data'
    parser.add_argument('--data-dir', default=os.environ.get('AQACOPILOT_DATA') or str(default_data))
    parser.add_argument('--warmup', action='store_true')
    args = parser.parse_args()
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    if not args.token or len(args.token) < 16:
        parser.error('A per-launch --token with at least 16 characters is required')
    if not 1024 <= args.port <= 65535:
        parser.error('port must be 1024–65535')
    # No access logging: it can expose query strings containing local text.
    import uvicorn
    from copilot.service import create_app
    application = create_app(Path(args.data_dir), args.token, startup_warmup=args.warmup)
    Path(args.data_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(Path(args.data_dir)/'backend-service.log'), level=logging.WARNING,
                        format='%(asctime)s %(levelname)s %(message)s')
    uvicorn.run(application, host='127.0.0.1', port=args.port, access_log=False, log_level='warning', use_colors=False)

if __name__ == '__main__':
    main()
