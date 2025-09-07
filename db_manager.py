import sqlite3
import os

DATABASE_NAME = os.path.expanduser('~/Documents/subtitles.db')
#DATABASE_NAME = 'Documents/subtitles.db'

def connect_db():
    return sqlite3.connect(DATABASE_NAME)

def create_tables():
    conn = connect_db()
    cursor = conn.cursor()
    
    # media_files table with phash for uniqueness
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS media_files (
            id INTEGER PRIMARY KEY,
            file_path TEXT UNIQUE,
            phash TEXT,
            modified_time INTEGER
        )
    ''')
    
    # subtitles table with a foreign key to media_files
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subtitles (
            id INTEGER PRIMARY KEY,
            media_id INTEGER,
            start_time REAL,
            end_time REAL,
            text TEXT,
            FOREIGN KEY (media_id) REFERENCES media_files(id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_last_modified_time():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute('SELECT MAX(modified_time) FROM media_files')
    last_time = cursor.fetchone()[0]
    conn.close()
    return last_time if last_time else 0

def insert_subtitles(media_id, subtitles_list):
    conn = connect_db()
    cursor = conn.cursor()
    
    # Convert subtitles to a list of tuples for batch insertion
    subtitle_data = [(media_id, sub['start_time'], sub['end_time'], sub['text']) for sub in subtitles_list]
    
    cursor.executemany('INSERT INTO subtitles (media_id, start_time, end_time, text) VALUES (?, ?, ?, ?)', subtitle_data)
    
    conn.commit()
    conn.close()

def insert_media_file(file_path, phash, modified_time):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO media_files (file_path, phash, modified_time) VALUES (?, ?, ?)',
            (file_path, phash, modified_time)
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        print(f"File {file_path} already exists in the database. Skipping.")
        return None
    finally:
        conn.close()

def get_media_id(file_path):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM media_files WHERE file_path = ?', (file_path,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None