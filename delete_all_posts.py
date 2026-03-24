#!/usr/bin/env python3
"""
Script to delete all posts from the database.
This will also delete related data (comments, likes, shares) due to cascade delete.
"""

from app import create_app
from models import db, Post

def delete_all_posts():
    """Delete all posts from the database"""
    app = create_app()
    with app.app_context():
        # Count posts before deletion
        post_count = Post.query.count()
        print(f"Found {post_count} posts to delete")

        if post_count == 0:
            print("✅ No posts to delete - database is already clean")
            return

        # Delete all posts (cascade will handle related data)
        try:
            Post.query.delete()
            db.session.commit()
            print(f"✅ Successfully deleted {post_count} posts and all related data")
            print("   - Comments deleted")
            print("   - Likes deleted")
            print("   - Shares deleted")
            print("   - Post metadata deleted")
            print("   - Image files remain in uploads/ folder")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error deleting posts: {e}")

if __name__ == '__main__':
    delete_all_posts()