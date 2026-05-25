#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path(tempfile.mkdtemp(prefix='violeta-perf-'))
DB_PATH = TEMP_ROOT / 'violeta_perf.sqlite3'
UPLOAD_DIR = TEMP_ROOT / 'uploads'

os.environ['SECRET_KEY'] = 'violeta-perf-secret'
os.environ['APP_ENV'] = 'development'
os.environ['DATABASE_URL'] = f'sqlite:///{DB_PATH}'
os.environ['DATABASE_REQUIRE_SSL'] = 'false'
os.environ['UPLOAD_BACKEND'] = 'local'
os.environ['UPLOAD_FOLDER'] = str(UPLOAD_DIR)
os.environ['REDIS_URL'] = ''
os.environ['SUPABASE_URL'] = ''
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = ''
os.environ['RESEND_API_KEY'] = ''
os.environ['MAIL_DELIVERY_METHOD'] = 'smtp'
os.environ['MAIL_SERVER'] = ''
os.environ['BACKGROUND_JOBS_INLINE'] = 'true'

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import Post, User, app, db  # noqa: E402


def seed_home_fixture() -> int:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(username='perf_home', email='perf_home@example.test')
        user.set_password('Password123')
        user.is_verified = True
        user.verification_status = 'verified'
        db.session.add(user)
        db.session.flush()

        for index in range(8):
            post = Post(
                user_id=user.id,
                caption=f'Reporte de rendimiento {index + 1}',
                image_filename='images/default_avatar.jpg',
                latitude=25.6866 + (index * 0.001),
                longitude=-100.3161 - (index * 0.001),
                location_name='Monterrey, Nuevo León',
                city='Monterrey',
                country='México',
                categories=json.dumps(['Zona insegura']),
            )
            db.session.add(post)

        db.session.commit()
        return int(user.id)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> int:
    user_id = seed_home_fixture()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    samples: list[float] = []
    server_timings: list[str] = []
    status_codes: list[int] = []

    for _ in range(7):
        started = time.perf_counter()
        response = client.get('/')
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        status_codes.append(response.status_code)
        server_timings.append(response.headers.get('Server-Timing', ''))
        samples.append(elapsed_ms)

    warm_samples = samples[1:]
    print('home_authenticated_perf_ms')
    print(f'  status_codes={status_codes}')
    print(f'  first={samples[0]:.1f}')
    print(f'  median={statistics.median(warm_samples):.1f}')
    print(f'  p95={percentile(warm_samples, 0.95):.1f}')
    print(f'  min={min(warm_samples):.1f}')
    print(f'  max={max(warm_samples):.1f}')
    print(f'  last_server_timing={server_timings[-1]}')
    return 0 if all(code == 200 for code in status_codes) else 1


if __name__ == '__main__':
    raise SystemExit(main())
