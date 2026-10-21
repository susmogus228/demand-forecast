"""Reproduce paired diagnostic v1 without changing frozen research artifacts."""
import argparse
import json
from pathlib import Path
from demand_forecast.diagnostics import build_diagnostics, markdown_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path('results'))
    parser.add_argument('--check', action='store_true', help='Verify existing derived outputs without writing')
    args = parser.parse_args()
    report = build_diagnostics(args.results)
    outputs = {'diagnostics-v1.json': json.dumps(report, indent=2, allow_nan=False)+'\n',
               'diagnostics-v1.md': markdown_report(report)}
    for name, text in outputs.items():
        path = args.results/name
        if args.check:
            if path.read_text(encoding='utf-8') != text:
                raise ValueError(f'{name} differs from the recomputed diagnostic.')
        else:
            path.write_text(text, encoding='utf-8')
    print(json.dumps({'status': 'verified' if args.check else 'written', 'n': report['overall']['n'],
                      'loss_counts': report['loss_counts']}))


if __name__ == '__main__':
    main()
