"""Google OIDC with explicit password confirmation for existing accounts."""
import secrets
import time
from urllib.parse import urlsplit

from authlib.integrations.flask_client import OAuth
from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from models import db, GoogleIdentity, User
from forms import GoogleRegistrationForm


def google_enabled():
    config = current_app.config
    uri = urlsplit(config.get('GOOGLE_REDIRECT_URI', ''))
    secure_uri = uri.scheme == 'https' or (
        config.get('APP_ENV') == 'development'
        and uri.scheme == 'http' and uri.hostname in {'localhost', '127.0.0.1'}
    )
    return bool(config.get('GOOGLE_CLIENT_ID') and config.get('GOOGLE_CLIENT_SECRET')
                and secure_uri and uri.netloc and not uri.fragment and not uri.query
                and uri.path == '/auth/google/callback')


def link_pending_google(user):
    """Called only after successful local password validation; fail closed on conflict."""
    pending = session.pop('google_link', None)
    if not pending or time.time() - pending.get('created_at', 0) > 600:
        return
    if pending.get('user_id') != user.id or pending.get('email') != user.email.lower():
        return
    if user.google_identity:
        return 'Esta cuenta ya tiene Google vinculado.', 'info'
    db.session.add(GoogleIdentity(subject=pending['subject'], user=user))
    try:
        db.session.commit()
        return 'Google quedó vinculado a tu cuenta.', 'success'
    except SQLAlchemyError:
        db.session.rollback()
        return 'No se pudo vincular Google. Tu acceso con contraseña sigue disponible.', 'warning'


def init_google_auth(app, finish_login, rate_limited):
    oauth = OAuth(app)
    google = oauth.register(
        name='google',
        client_id=app.config.get('GOOGLE_CLIENT_ID'),
        client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256', 'timeout': 10},
    )
    app.extensions['violeta_google_client'] = google

    @app.context_processor
    def google_context():
        return {'google_login_enabled': google_enabled()}

    @app.route('/auth/google', methods=['POST'])
    def google_login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if not google_enabled():
            flash('El acceso con Google todavía no está configurado.', 'info')
            return redirect(url_for('login'))
        if rate_limited():
            return 'Demasiados intentos. Intenta de nuevo en unos minutos.', 429
        session.pop('google_link', None)
        session.pop('google_signup', None)
        session['google_remember'] = request.form.get('remember') in {'1', 'true', 'on'}
        try:
            # Authlib persists and verifies state, nonce and the PKCE verifier.
            return google.authorize_redirect(app.config['GOOGLE_REDIRECT_URI'], prompt='select_account')
        except Exception:
            session.pop('google_remember', None)
            app.logger.warning('Google authorization could not be started')
            flash('No pudimos conectar con Google. Intenta otra vez o usa tu contraseña.', 'warning')
            return redirect(url_for('login'))

    @app.route('/auth/google/callback')
    def google_callback():
        if not google_enabled():
            return redirect(url_for('login'))
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if rate_limited():
            return 'Demasiados intentos. Intenta de nuevo en unos minutos.', 429
        remember = session.pop('google_remember', False)
        try:
            # Includes signature, issuer, audience, expiration, state and nonce validation.
            token = google.authorize_access_token()
            claims = (token.get('userinfo') or {}) if token.get('id_token') else {}
            subject = claims.get('sub')
            email = claims.get('email')
            if (not isinstance(subject, str) or not subject or len(subject) > 255
                    or claims.get('email_verified') is not True
                    or not isinstance(email, str) or '@' not in email or len(email) > 120):
                raise ValueError('Invalid identity claims')
            email = email.strip().lower()
            identity = GoogleIdentity.query.filter_by(subject=subject).first()
            if identity:
                user = identity.user
            else:
                existing = User.query.filter(func.lower(User.email) == email).first()
                if existing:
                    session['google_link'] = {'subject': subject, 'email': email,
                                              'user_id': existing.id, 'created_at': time.time()}
                    flash('Para vincular Google, inicia sesión con la contraseña de tu cuenta de Violeta. Si no la recuerdas, recupérala primero.', 'info')
                    return redirect(url_for('login'))
                session['google_signup'] = {'subject': subject, 'email': email,
                                            'remember': remember, 'created_at': time.time()}
                return redirect(url_for('google_complete'))
        except Exception:
            db.session.rollback()
            # Provider exceptions may contain credentials; never log their payloads.
            app.logger.warning('Google sign-in failed or was cancelled')
            flash('No se completó el acceso con Google. Intenta otra vez o usa tu contraseña.', 'warning')
            return redirect(url_for('login'))
        return finish_login(user, remember)

    @app.route('/auth/google/complete', methods=['GET', 'POST'])
    def google_complete():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        pending = session.get('google_signup')
        if not google_enabled() or not pending or time.time() - pending.get('created_at', 0) > 600:
            session.pop('google_signup', None)
            flash('Vuelve a iniciar con Google para completar tu registro.', 'info')
            return redirect(url_for('login'))
        form = GoogleRegistrationForm()
        if form.validate_on_submit():
            try:
                # Do not bypass the eligibility attestation required by local registration.
                if (User.query.filter(func.lower(User.email) == pending['email']).first()
                        or GoogleIdentity.query.filter_by(subject=pending['subject']).first()):
                    session.pop('google_signup', None)
                    flash('La cuenta ya existe. Vuelve a iniciar sesión para vincularla.', 'info')
                    return redirect(url_for('login'))
                # Never derive privileged usernames from Google profile data.
                user = User(username='usuaria_' + secrets.token_hex(6), email=pending['email'],
                            is_verified=False, verification_status='unverified', trial_location_views_limit=3)
                user.set_password(secrets.token_urlsafe(48))
                db.session.add(user)
                db.session.add(GoogleIdentity(subject=pending['subject'], user=user))
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                flash('No pudimos crear tu cuenta. Intenta de nuevo.', 'warning')
                return render_template('google_complete.html', form=form), 409
            return finish_login(user, pending.get('remember', False))
        return render_template('google_complete.html', form=form)
