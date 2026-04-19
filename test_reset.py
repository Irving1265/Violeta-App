from app import app, db
from models import User
from app import generate_temporary_password

with app.app_context():
    user = User.query.get(9)
    print("User:", user)
    temporary_password = generate_temporary_password()
    print("Temp pwd:", temporary_password)
    user.set_password(temporary_password)
    user.force_password_change = True
    user.password_recovery_requested_at = None
    db.session.add(user)
    db.session.commit()
    print('Success')
