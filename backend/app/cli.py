import argparse
import getpass
from sqlalchemy import select
from .config import Settings
from .database import User, create_database
from .services.security import hasher


def main():
    parser = argparse.ArgumentParser(prog='rootdrive')
    parser.add_argument('command', choices=['create-admin', 'serve'])
    parser.add_argument('--username')
    arguments = parser.parse_args()
    settings = Settings()
    settings.prepare()
    if arguments.command == 'serve':
        import uvicorn
        uvicorn.run('app.main:create_app', factory=True, host=settings.host, port=settings.port)
        return
    username = arguments.username or input('Username: ').strip()
    if not username or len(username) > 80:
        parser.error('Username must contain 1 to 80 characters')
    password = getpass.getpass('Password: ')
    if len(password) < 10 or password != getpass.getpass('Confirm password: '):
        parser.error('Passwords must match and contain at least 10 characters')
    engine, sessions = create_database(settings.database_path)
    with sessions() as db:
        if db.scalar(select(User).where(User.username == username)):
            parser.error('Username already exists')
        db.add(User(username=username, password_hash=hasher.hash(password), role='admin'))
        db.commit()
    engine.dispose()
    print('Administrator created')


if __name__ == '__main__':
    main()
