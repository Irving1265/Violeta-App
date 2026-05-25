#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_step(label: str, command: list[str]) -> None:
    print(f'\n==> {label}', flush=True)
    # Commands are static lists controlled by this script; shell stays disabled.
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)  # nosec B603


def main() -> int:
    python = sys.executable
    os.environ.setdefault('PYTHONUNBUFFERED', '1')
    os.environ.setdefault('APP_ENV', 'development')
    os.environ.setdefault('BACKGROUND_JOBS_INLINE', 'true')

    run_step(
        'Compilar archivos Python criticos',
        [
            python,
            '-m',
            'py_compile',
            'app.py',
            'config.py',
            'forms.py',
            'models.py',
            'scripts/perf_home_check.py',
            'scripts/smoke_test_cases.py',
        ],
    )
    run_step(
        'Bandit sin hallazgos High',
        [
            python,
            '-m',
            'bandit',
            '-r',
            'app.py',
            'models.py',
            'config.py',
            'forms.py',
            'scripts',
            '-x',
            'scripts/smoke_test_cases.py,scripts/ui_browser_smoke.py',
            '-lll',
        ],
    )
    run_step('Smoke tests criticos', [python, 'scripts/smoke_test_cases.py'])
    run_step(
        'Preflight no estricto',
        [
            python,
            '-m',
            'flask',
            '--app',
            'app:app',
            'preflight-check',
        ],
    )
    if os.environ.get('RUN_UI_SMOKE') == '1':
        run_step('Smoke visual telefono/web', [python, 'scripts/ui_browser_smoke.py'])
    else:
        print('\n==> Smoke visual telefono/web omitido (usa RUN_UI_SMOKE=1 para ejecutarlo)', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
