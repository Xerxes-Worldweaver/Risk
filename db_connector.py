import sqlite3 as sql
import json

db = sql.connect("risk.db")
cursor = db.cursor()

def ensure_user_exists(user_id: int, guild_id: int) -> None:
    """Adds a user/guild pair to the roster; users have a unique game pointer for every guild."""
    try:
        cursor.execute("INSERT INTO users (user_id, guild_id, game_id) VALUES (?, ?, NULL)", (user_id, guild_id))
        db.commit()
    except sql.IntegrityError:
        pass

def create_game(game_data: dict) -> int:
    """Creates game with data in provided dictionary and returns the database-generated game id."""
    cursor.execute("INSERT INTO games (game_data) VALUES (?)", (json.dumps(game_data),))
    db.commit()
    cursor.execute("SELECT MAX(game_id) FROM games")
    return cursor.fetchone()[0]

def get_user_game_id(user_id: int, guild_id: int) -> int:
    """Returns the id of a user's game or None if there is no game."""
    cursor.execute("SELECT game_id FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
    id = cursor.fetchone()
    if id != None:
        id = id[0]
    return id

def get_user_game_data(user_id: int, guild_id: int) -> dict:
    """Returns the de-jsonified game data that a user/guild pair points to, or None if there is no game."""
    cursor.execute("SELECT game_data FROM games WHERE game_id = (SELECT game_id FROM users WHERE user_id = ? AND guild_id = ?)", (user_id, guild_id))
    data = cursor.fetchone()
    if data != None:
        data = json.loads(data[0])
    return data

def update_user_game_pointer(user_id: int, guild_id: int, game_id: int) -> None:
    """Changes a user's game id pointer or sets it to null."""
    cursor.execute("UPDATE users SET game_id = ? WHERE user_id = ? AND guild_id = ?", (game_id, user_id, guild_id))
    db.commit()

def update_user_game_data(user_id: int, guild_id: int, game_data: dict) -> None:
    """Updates the data of the user's current game."""
    cursor.execute("UPDATE games SET game_data = ? WHERE game_id = (SELECT game_id FROM users WHERE user_id = ? AND guild_id = ?)", (json.dumps(game_data), user_id, guild_id))
    db.commit()

def update_game(game_id: int, game_data: dict) -> None:
    """Updates game data."""
    cursor.execute("UPDATE games SET game_data = ? WHERE ROWID = ?", (json.dumps(game_data), game_id))
    db.commit()

def delete_game(game_id: int) -> None:
    """Removes game from database."""
    cursor.execute("DELETE FROM games WHERE ROWID = ?", (game_id,))
    db.commit()

def increment_rigged_counter() -> int:
    """Adds 1 to the rigged counter and returns the new rigged count."""
    cursor.execute("UPDATE rigged SET count = count + 1")
    db.commit()
    cursor.execute("SELECT count FROM rigged")
    return cursor.fetchone()[0]