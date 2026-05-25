#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SmokeCheck:
    path: str
    expected_status: int = 200
    must_contain: str | None = None
    expects_health_ok: bool = False


CHECKS = (
    SmokeCheck('/healthz', must_contain='"status":"ok"', expects_health_ok=True),
    SmokeCheck('/privacy', must_contain='Política de privacidad'),
    SmokeCheck('/account/delete', must_contain='Eliminar cuenta'),
    SmokeCheck('/beta', must_contain='Beta v1.0'),
    SmokeCheck('/support', must_contain='Reportar problema'),
    SmokeCheck('/terms', must_contain='Términos de uso'),
)


def fetch(url: str, timeout: float) -> tuple[int, str]:
    scheme = urlsplit(url).scheme.lower()
    if scheme not in {'http', 'https'}:
        raise ValueError(f'Esquema no permitido para smoke test: {scheme or "sin esquema"}')
    request = Request(url, headers={'User-Agent': 'VioletaProductionSmoke/1.0'})
    try:
        # URL scheme is restricted above.
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            body = response.read().decode('utf-8', errors='replace')
            return int(response.status), body
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        return int(exc.code), body
    except URLError as exc:
        raise RuntimeError(f'No se pudo conectar: {exc.reason}') from exc


def run_checks(base_url: str, timeout: float) -> tuple[bool, list[dict[str, object]]]:
    normalized_base = base_url.rstrip('/') + '/'
    results: list[dict[str, object]] = []
    ok = True

    for check in CHECKS:
        url = urljoin(normalized_base, check.path.lstrip('/'))
        result: dict[str, object] = {'path': check.path, 'url': url}
        try:
            status, body = fetch(url, timeout)
            result['status_code'] = status
            result['ok'] = status == check.expected_status
            if check.must_contain:
                contains_expected = check.must_contain in body
                result['contains_expected_text'] = contains_expected
                result['ok'] = bool(result['ok']) and contains_expected
            if check.expects_health_ok:
                try:
                    payload = json.loads(body)
                    health_ok = payload.get('status') == 'ok'
                except json.JSONDecodeError:
                    health_ok = False
                result['health_ok'] = health_ok
                result['ok'] = bool(result['ok']) and health_ok
        except Exception as exc:  # noqa: BLE001
            result['ok'] = False
            result['error'] = str(exc)

        ok = ok and bool(result['ok'])
        results.append(result)

    return ok, results


def main() -> int:
    parser = argparse.ArgumentParser(description='Smoke test público de producción para Violeta.')
    parser.add_argument(
        '--base-url',
        default='https://violeta-app.onrender.com',
        help='URL base pública de producción.',
    )
    parser.add_argument('--timeout', type=float, default=20.0, help='Timeout por request en segundos.')
    args = parser.parse_args()

    ok, results = run_checks(args.base_url, args.timeout)
    print(json.dumps({'ok': ok, 'base_url': args.base_url, 'checks': results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
