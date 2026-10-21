"""Command-line entry points; the web adapter loads only for demo."""

import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Daily midnight bicycle-demand forecasts and historical evaluation.')
    commands = parser.add_subparsers(dest='command', required=True)
    fitting = commands.add_parser('train', help='Download UCI data and run the frozen protocol.')
    fitting.add_argument('--output', type=Path, default=Path('results'))
    fitting.add_argument('--source', type=Path, help='Use an authorized local hour.csv instead of UCI download.')
    forecast = commands.add_parser('forecast', help='Forecast one origin using a trusted local artifact.')
    forecast.add_argument('--results', type=Path, default=Path('results'))
    forecast.add_argument('--origin', required=True)
    forecast.add_argument('--history', type=Path, help='JSON array of explicit historical timestamp/count records.')
    demo = commands.add_parser('demo', help='Serve the local app and API on 127.0.0.1.')
    demo.add_argument('--results', type=Path, default=Path('results'))
    demo.add_argument('--port', type=int, default=8766)
    args = parser.parse_args(argv)
    try:
        if args.command == 'train':
            from .training import train
            value = train(args.output, source_path=args.source)
            print(json.dumps(value, indent=2, allow_nan=False))
        elif args.command == 'forecast':
            from .service import ForecastService
            history = json.loads(args.history.read_text(encoding='utf-8')) if args.history else None
            print(json.dumps(ForecastService(args.results).forecast(args.origin, history), indent=2, allow_nan=False))
        else:
            from .demo import serve
            serve(args.results, args.port)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    return 0
