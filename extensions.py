import sqlite3

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_session import Session
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
login_manager = LoginManager()
server_session = Session()
csrf = CSRFProtect()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
	if not isinstance(dbapi_connection, sqlite3.Connection):
		return

	cursor = dbapi_connection.cursor()
	try:
		cursor.execute("PRAGMA foreign_keys=ON")
	finally:
		cursor.close()