"""
manage.py
---------
Optional command-line helpers. Most things are done in the web UI now, but these
are handy for first-time setup or recovery. Run from the backend/ folder.

  python manage.py create-admin           # create an approved admin account
  python manage.py list-users             # show all users and their status
  python manage.py approve <user_id>      # approve a pending access request
  python manage.py make-admin <user_id>   # promote a user to admin

The web UI normally handles all of this; create-admin is just an alternative to
the first-run setup screen.
"""

import sys
import getpass

import database
import auth

USAGE = __doc__


def main():
    database.init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "create-admin":
        email = input("Email: ").strip()
        if not email or "@" not in email:
            print("Invalid email."); sys.exit(1)
        if database.get_user_by_email(email):
            print("A user with that email already exists."); sys.exit(1)
        name = input("Name (optional): ").strip()
        p1 = getpass.getpass("Password: ")
        p2 = getpass.getpass("Confirm: ")
        if p1 != p2 or len(p1) < 8:
            print("Passwords must match and be 8+ characters."); sys.exit(1)
        database.create_user(
            email=email, name=name, password_hash=auth.hash_password(p1),
            status="approved", role="admin",
        )
        print(f"✓ Admin created: {email}")

    elif cmd == "list-users":
        users = database.list_users()
        if not users:
            print("No users yet. Run: python manage.py create-admin")
        else:
            print(f"{'id':<4}{'email':<30}{'role':<8}{'status'}")
            for u in users:
                print(f"{u['id']:<4}{u['email']:<30}{u['role']:<8}{u['status']}")

    elif cmd == "approve":
        if len(sys.argv) < 3:
            print("Usage: python manage.py approve <user_id>"); sys.exit(1)
        u = database.update_user(int(sys.argv[2]), {"status": "approved"})
        print(f"✓ Approved: {u['email']}" if u else "No such user.")

    elif cmd == "make-admin":
        if len(sys.argv) < 3:
            print("Usage: python manage.py make-admin <user_id>"); sys.exit(1)
        u = database.update_user(int(sys.argv[2]), {"role": "admin", "status": "approved"})
        print(f"✓ {u['email']} is now an admin." if u else "No such user.")

    else:
        print(USAGE)


if __name__ == "__main__":
    main()
