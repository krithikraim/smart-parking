# create_admin.py
# Standalone script to create or promote a user to admin in SmartPark

from getpass import getpass
from app import app, db
from app import User  # Ensure app.py exports User
from werkzeug.security import generate_password_hash


def create_admin_user():
    username = input('Enter the admin username: ').strip()
    if not username:
        print('Username cannot be empty.')
        return
    password = getpass('Enter password: ').strip()
    if not password:
        print('Password cannot be empty.')
        return

    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if user:
            user.role = 'admin'
            user.password_hash = generate_password_hash(password)
            print(f"Updated existing user '{username}' to admin.")
        else:
            new_admin = User(
                username=username,
                password_hash=generate_password_hash(password),
                role='admin'
            )
            db.session.add(new_admin)
            print(f"Created new admin user '{username}'.")
        db.session.commit()
    print('Admin setup complete.')


if __name__ == '__main__':
    create_admin_user()

# -----------------------------------------------------------------------------
# After running this script, update your login() in app.py as follows:
#
# In the POST handling of /login:
#     if user and check_password_hash(user.password_hash, password):
#         login_user(user)
#         if user.role == 'admin':
#             return redirect(url_for('admin_dashboard'))
#         return redirect(url_for('dashboard'))
#
# This ensures admins go to the admin panel by default.
