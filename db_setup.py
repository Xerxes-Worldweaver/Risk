import sqlite3 as sql

con = sql.connect("risk.db")
cur = con.cursor()

cur.execute(
    """
    CREATE TABLE users (
        user_id INTEGER NOT NULL,
        guild_id INTEGER NOT NULL,
        game_id INTEGER,
        PRIMARY KEY (user_id, guild_id)
    );
    """
)
cur.execute(
    """
    CREATE TABLE games (
        game_id INTEGER NOT NULL PRIMARY KEY,
        game_data TEXT NOT NULL
    );
    """
)
cur.execute(
    """
    CREATE TABLE rigged (
        count INTEGER NOT NULL
    );
    """
)
cur.execute(
    """
    INSERT INTO rigged (count) VALUES (0);
    """
)

con.commit()
con.close()