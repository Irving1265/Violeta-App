#!/usr/bin/env python3
"""
Script to export all users from the database to an Excel file.
"""

import pandas as pd
from app import create_app
from models import User

def export_users_to_excel():
    """Export all users to Excel file"""
    app, _socketio = create_app()
    with app.app_context():
        # Query all users
        users = User.query.all()

        # Prepare data for Excel
        user_data = []
        for user in users:
            user_data.append({
                'ID': user.id,
                'Username': user.username,
                'Email': user.email,
                'Profile_Pic': user.profile_pic,
                'Bio': user.bio,
                'Created_At': user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else None
            })

        # Create DataFrame
        df = pd.DataFrame(user_data)

        # Export to Excel
        output_file = 'Usuarios.xlsx'
        df.to_excel(output_file, index=False, engine='openpyxl')

        print(f"✅ Exported {len(user_data)} users to '{output_file}'")

        return output_file

if __name__ == '__main__':
    export_users_to_excel()
