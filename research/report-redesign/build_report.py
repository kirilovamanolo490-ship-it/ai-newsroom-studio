"""Render a reviewed morning/evening issue through the single maintained renderer."""
from pathlib import Path
import argparse
from build_edition_report import build
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True,help='Reviewed report.json for the issue to render')
    build(parser.parse_args().input)
