"""Tiny PyMySQL helper. Use `with transaction() as cur:` for atomic work."""
import pymysql, pymysql.cursors
from contextlib import contextmanager
import config

def connect():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, autocommit=False, **config.DB)

@contextmanager
def transaction():
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def query(sql, args=None, one=False):
    with transaction() as cur:
        cur.execute(sql, args or ())
        return cur.fetchone() if one else cur.fetchall()
