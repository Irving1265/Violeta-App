import argparse
import mimetypes
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from dotenv import load_dotenv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Sincroniza archivos publicos de static/uploads a Supabase Storage.'
    )
    parser.add_argument(
        '--uploads-dir',
        default='static/uploads',
        help='Directorio local de uploads a sincronizar (por defecto: static/uploads).',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Solo muestra que archivos se subirian, sin subirlos.',
    )
    return parser


def required_env(name: str) -> str:
    value = (os.environ.get(name) or '').strip()
    if not value:
        raise SystemExit(f'Falta la variable de entorno requerida: {name}')
    return value


def upload_file(base_url: str, api_key: str, bucket: str, local_path: Path, storage_path: str, dry_run: bool) -> bool:
    mime_type = mimetypes.guess_type(str(local_path))[0] or 'application/octet-stream'
    endpoint = f"{base_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(storage_path, safe='/')}"
    if dry_run:
        print(f'DRY RUN {storage_path} <- {local_path}')
        return True

    data = local_path.read_bytes()
    request = Request(
        endpoint,
        data=data,
        headers={
            'Authorization': f'Bearer {api_key}',
            'apikey': api_key,
            'Content-Type': mime_type,
            'x-upsert': 'true',
        },
        method='POST',
    )
    try:
        with urlopen(request, timeout=60) as response:  # nosec B310
            status = getattr(response, 'status', None) or response.getcode()
            return status in (200, 201)
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        print(f'ERROR {storage_path}: HTTP {exc.code} {detail}')
        return False
    except URLError as exc:
        print(f'ERROR {storage_path}: {exc}')
        return False


def iter_public_files(root: Path):
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith('verify/'):
            continue
        yield path, relative


if __name__ == '__main__':
    load_dotenv()
    args = build_parser().parse_args()

    uploads_dir = Path(args.uploads_dir).resolve()
    if not uploads_dir.exists():
        raise SystemExit(f'No existe el directorio: {uploads_dir}')

    base_url = required_env('SUPABASE_URL').rstrip('/')
    api_key = required_env('SUPABASE_SERVICE_ROLE_KEY')
    bucket = (os.environ.get('SUPABASE_STORAGE_BUCKET') or 'uploads').strip()

    total = 0
    ok = 0
    failed = 0
    for local_path, storage_path in iter_public_files(uploads_dir):
        total += 1
        if upload_file(base_url, api_key, bucket, local_path, storage_path, args.dry_run):
            ok += 1
            print(f'OK {storage_path}')
        else:
            failed += 1

    print('---')
    print(f'Total: {total}')
    print(f'OK: {ok}')
    print(f'Failed: {failed}')
    if failed:
        raise SystemExit(1)
