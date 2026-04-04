from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


db = SQLAlchemy()

# --- Etiquetas / Peligros ----------------------------------------------------

# Tabla de asociación Post-Tag (muchos a muchos)
post_tag = db.Table(
    'post_tag',
    db.Column('post_id', db.Integer, db.ForeignKey('post.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True),
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    roles = db.Column(db.Text)
    profile_pic = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_verified = db.Column(db.Boolean, default=True)
    abuse_strikes = db.Column(db.Integer, default=0)
    muted_until = db.Column(db.DateTime)
    last_abuse_at = db.Column(db.DateTime)
    permanently_banned_at = db.Column(db.DateTime)
    permanent_ban_reason = db.Column(db.String(255))

    # Relaciones
    posts = db.relationship('Post', back_populates='author', lazy=True, cascade='all, delete-orphan')
    comments = db.relationship('Comment', back_populates='author', lazy=True, cascade='all, delete-orphan')
    likes = db.relationship('Like', back_populates='user', lazy=True, cascade='all, delete-orphan')
    moderation_strikes = db.relationship('ModerationStrike', back_populates='user', lazy=True, cascade='all, delete-orphan', foreign_keys='ModerationStrike.user_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def role_set(self) -> set[str]:
        raw = (self.roles or '').strip()
        if not raw:
            return set()
        parts = set()
        for chunk in raw.split(','):
            role = chunk.strip().lower()
            if role:
                parts.add(role)
        return parts

    def has_role(self, role: str) -> bool:
        normalized = (role or '').strip().lower()
        if not normalized:
            return False
        return normalized in self.role_set()

    def has_any_role(self, *roles: str) -> bool:
        current = self.role_set()
        if not current:
            return False
        for role in roles:
            normalized = (role or '').strip().lower()
            if normalized and normalized in current:
                return True
        return False

    def set_roles(self, roles) -> None:
        normalized = sorted({
            str(role).strip().lower()
            for role in (roles or [])
            if str(role).strip()
        })
        self.roles = ','.join(normalized) if normalized else None

    def __repr__(self):
        return f'<User {self.username}>'


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    caption = db.Column(db.Text)
    image_filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    publish_at = db.Column(db.DateTime)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Campos de geolocalización
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    location_name = db.Column(db.String(255))
    city = db.Column(db.String(100))
    country = db.Column(db.String(100))

    # Categorías (almacenadas como JSON)
    categories = db.Column(db.Text)  # JSON string con lista de categorías

    # Relaciones
    author = db.relationship('User', back_populates='posts')
    comments = db.relationship('Comment', back_populates='post', lazy=True, cascade='all, delete-orphan')
    likes = db.relationship('Like', back_populates='post', lazy=True, cascade='all, delete-orphan')
    tags = db.relationship('Tag', secondary=post_tag, lazy='subquery', backref=db.backref('posts', lazy=True))

    def get_likes_count(self):
        return len(self.likes)  # type: ignore

    def get_comments_count(self):
        return len(self.comments)  # type: ignore

    def is_liked_by(self, user):
        if not user.is_authenticated:
            return False
        return Like.query.filter_by(user_id=user.id, post_id=self.id).first() is not None

    def __repr__(self):
        return f'<Post {self.id}>'


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Tag {self.name}>'


class PostMeta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), unique=True, nullable=False)
    alt_text = db.Column(db.String(255))
    show_public = db.Column(db.Boolean, default=True)
    allow_likes = db.Column(db.Boolean, default=True)
    allow_comments = db.Column(db.Boolean, default=True)
    location_visibility = db.Column(db.String(20), default='exact')  # exact, approx, hidden
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship('Post', backref=db.backref('meta', uselist=False, cascade='all, delete-orphan'))


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    is_hidden = db.Column(db.Boolean, default=False)
    hidden_at = db.Column(db.DateTime)
    hidden_by = db.Column(db.Integer)
    hidden_reason = db.Column(db.String(32))

    # Relaciones
    author = db.relationship('User', back_populates='comments')
    post = db.relationship('Post', back_populates='comments')
    reports = db.relationship('CommentReport', back_populates='comment', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Comment {self.id}>'


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Índice único para evitar likes duplicados
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_like'),)

    # Relaciones
    user = db.relationship('User', back_populates='likes')
    post = db.relationship('Post', back_populates='likes')

    def __repr__(self):
        return f'<Like {self.user_id}-{self.post_id}>'


class Share(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)

    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])
    post = db.relationship('Post', foreign_keys=[post_id])

    def __repr__(self):
        return f'<Share {self.sender_id}-{self.receiver_id}-{self.post_id}>'


class UserBlock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_muted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    blocker = db.relationship('User', foreign_keys=[blocker_id], backref=db.backref('blocked_users', lazy=True))
    blocked = db.relationship('User', foreign_keys=[blocked_id], backref=db.backref('blocked_by_users', lazy=True))

    __table_args__ = (db.UniqueConstraint('blocker_id', 'blocked_id', name='unique_user_block_pair'),)

    def __repr__(self):
        return f'<UserBlock {self.blocker_id}->{self.blocked_id}>'


class SafetyContact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(24), nullable=False)
    relationship = db.Column(db.String(80))
    is_primary = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('safety_contacts', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<SafetyContact {self.user_id}:{self.phone}>'


class PanicEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(24))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    note = db.Column(db.String(255))
    status = db.Column(db.String(20), default='open')  # open, resolved
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey('user.id'))

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('panic_events', lazy=True, cascade='all, delete-orphan'))
    resolver = db.relationship('User', foreign_keys=[resolved_by], backref=db.backref('resolved_panic_events', lazy=True))

    def __repr__(self):
        return f'<PanicEvent {self.id}:{self.user_id}:{self.status}>'


class SafetyCheckin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Editable label for the trip (defaults to "Trayecto N" when the user arrives).
    title = db.Column(db.String(180))
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(24))
    destination = db.Column(db.String(180))
    note = db.Column(db.String(255))
    eta_minutes = db.Column(db.Integer, default=30)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='active')  # active, arrived, cancelled, expired
    arrived_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    triggered_panic_id = db.Column(db.Integer, db.ForeignKey('panic_event.id'))

    user = db.relationship('User', backref=db.backref('safety_checkins', lazy=True, cascade='all, delete-orphan'))
    triggered_panic = db.relationship('PanicEvent', foreign_keys=[triggered_panic_id])

    def __repr__(self):
        return f'<SafetyCheckin {self.id}:{self.user_id}:{self.status}>'


class CheckinRoutePoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    checkin_id = db.Column(db.Integer, db.ForeignKey('safety_checkin.id'), nullable=False, index=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    speed_kmh = db.Column(db.Float)
    accuracy_m = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    checkin = db.relationship('SafetyCheckin', backref=db.backref('route_points', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<CheckinRoutePoint {self.checkin_id}:{self.latitude},{self.longitude}>'


# --- Chat Models ----------------------------------------------------

class ChatRoom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_private = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=True)
    messages_open = db.Column(db.Boolean, default=True)
    image_filename = db.Column(db.String(255))
    description = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    messages = db.relationship('ChatMessage', back_populates='room', lazy=True, cascade='all, delete-orphan')
    participants = db.relationship('ChatParticipant', back_populates='room', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ChatRoom {self.name}>'


class ChatParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('chat_room.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_read_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    user = db.relationship('User', backref=db.backref('chat_participations', lazy=True))
    room = db.relationship('ChatRoom', back_populates='participants')

    __table_args__ = (db.UniqueConstraint('user_id', 'room_id', name='unique_participant'),)

    def __repr__(self):
        return f'<ChatParticipant {self.user_id}-{self.room_id}>'


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('chat_room.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    message_type = db.Column(db.String(20), default='text')  # text, image, system
    attachment_filename = db.Column(db.String(255))
    attachment_name = db.Column(db.String(255))
    attachment_mime = db.Column(db.String(120))
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime)
    deleted_by = db.Column(db.Integer, db.ForeignKey('user.id'))

    # Relaciones
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('chat_messages', lazy=True))
    deleted_by_user = db.relationship('User', foreign_keys=[deleted_by], backref=db.backref('deleted_chat_messages', lazy=True))
    room = db.relationship('ChatRoom', back_populates='messages')
    reports = db.relationship('ChatMessageReport', back_populates='message', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ChatMessage {self.user_id}-{self.room_id}>'


# --- Reports ----------------------------------------------------

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, reviewing, resolved, dismissed, restored, struck
    admin_note = db.Column(db.Text)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship('Post', backref=db.backref('reports', lazy=True, cascade='all, delete-orphan'))
    reporter = db.relationship('User', foreign_keys=[reporter_id], backref=db.backref('reports', lazy=True))
    resolver = db.relationship('User', foreign_keys=[resolved_by], backref=db.backref('resolved_reports', lazy=True))

    __table_args__ = (db.UniqueConstraint('post_id', 'reporter_id', name='unique_reporter_post'),)

    def __repr__(self):
        return f'<Report {self.post_id}-{self.reporter_id}>'


class ChatMessageReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_message.id'), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, reviewing, resolved, dismissed, restored, struck
    admin_note = db.Column(db.Text)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    message = db.relationship('ChatMessage', back_populates='reports')
    reporter = db.relationship('User', foreign_keys=[reporter_id], backref=db.backref('chat_message_reports', lazy=True))
    resolver = db.relationship('User', foreign_keys=[resolved_by], backref=db.backref('resolved_chat_message_reports', lazy=True))

    __table_args__ = (db.UniqueConstraint('message_id', 'reporter_id', name='unique_reporter_chat_message'),)

    def __repr__(self):
        return f'<ChatMessageReport {self.message_id}-{self.reporter_id}>'


class CommentReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, reviewing, resolved, dismissed, restored, struck
    admin_note = db.Column(db.Text)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    comment = db.relationship('Comment', back_populates='reports')
    reporter = db.relationship('User', foreign_keys=[reporter_id], backref=db.backref('comment_reports', lazy=True))
    resolver = db.relationship('User', foreign_keys=[resolved_by], backref=db.backref('resolved_comment_reports', lazy=True))

    __table_args__ = (db.UniqueConstraint('comment_id', 'reporter_id', name='unique_reporter_comment'),)

    def __repr__(self):
        return f'<CommentReport {self.comment_id}-{self.reporter_id}>'


class ModerationStrike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    issued_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    source_type = db.Column(db.String(32), nullable=False)
    source_id = db.Column(db.Integer)
    source_label = db.Column(db.String(255))
    reason = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text)
    content_excerpt = db.Column(db.Text)
    strike_number = db.Column(db.Integer, nullable=False)
    consequence = db.Column(db.String(32), default='warning')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], back_populates='moderation_strikes')
    issuer = db.relationship('User', foreign_keys=[issued_by], backref=db.backref('issued_moderation_strikes', lazy=True))

    def __repr__(self):
        return f'<ModerationStrike {self.user_id}:{self.strike_number}:{self.source_type}>'


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    event_type = db.Column(db.String(64), nullable=False, index=True)
    workspace = db.Column(db.String(64), index=True)
    resource_type = db.Column(db.String(64))
    resource_id = db.Column(db.Integer)
    route = db.Column(db.String(255))
    method = db.Column(db.String(10))
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    summary = db.Column(db.String(255))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    actor = db.relationship('User', foreign_keys=[actor_id], backref=db.backref('audit_events', lazy=True))
    target_user = db.relationship('User', foreign_keys=[target_user_id], backref=db.backref('targeted_audit_events', lazy=True))

    __table_args__ = (
        db.Index('ix_audit_log_workspace_created_at', 'workspace', 'created_at'),
    )

    def __repr__(self):
        return f'<AuditLog {self.event_type}:{self.actor_id}:{self.created_at}>'


# --- Verification ----------------------------------------------------

class VerificationRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    phone = db.Column(db.String(20))
    phone_verified_at = db.Column(db.DateTime)
    otp_code = db.Column(db.String(10))
    otp_expires_at = db.Column(db.DateTime)
    video_filename = db.Column(db.String(255))
    status = db.Column(db.String(20), default='draft')  # draft, pending, approved, rejected
    liveness_phrase = db.Column(db.String(128))
    admin_notes = db.Column(db.Text)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('verification_requests', lazy=True))
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])

    def __repr__(self):
        return f'<VerificationRequest {self.user_id}-{self.status}>'
