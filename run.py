import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'backend'))
from app.cli import main

if __name__ == '__main__':
    if len(sys.argv) == 1:
        sys.argv.append('serve')
    main()
