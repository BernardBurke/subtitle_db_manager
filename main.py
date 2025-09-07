import argparse
import os
import re
import db_manager
import file_walker
import subtitle_parser
from datetime import datetime

def convert_time_to_seconds(start_time, end_time):
    """Calculates the length of a subtitle entry in seconds."""
    return end_time - start_time

def write_edl_file(search_results, query_str):
    """Generates a string in mpv EDL format and writes to a file."""
    
    # Sanitize query string for a safe filename
    safe_query = re.sub(r'[^a-zA-Z0-9_]+', '_', query_str)
    edl_filename = f"{safe_query}.edl"
    edl_path = os.path.join('/tmp', edl_filename)
    
    with open(edl_path, 'w') as f:
        for result in search_results:
            file_path, start_time, length = result
            # EDL format: file_path, start_time, length
            f.write(f"{file_path},{start_time:.2f},{length:.2f}\n")
    
    print(f"\nEDL file saved to: {edl_path}")

def load_subtitles(directory_path, reload=False):
    """Handles loading or updating the database with subtitles."""
    if reload:
        print("Recreating database...")
        if os.path.exists(db_manager.DATABASE_NAME):
            os.remove(db_manager.DATABASE_NAME)
        db_manager.create_tables()

    last_modified_time = db_manager.get_last_modified_time()
    
    file_pairs = file_walker.find_media_and_subtitles(directory_path)
    print(f"Found {len(file_pairs)} media/subtitle pairs.")

    for pair in file_pairs:
        media_path = pair['media_path']
        subtitle_path = pair['subtitle_path']
        
        mod_time = os.path.getmtime(media_path)
        if not reload and mod_time <= last_modified_time:
            print(f"Skipping {media_path} (not modified since last update).")
            continue

        print(f"Processing {media_path}...")
        
        media_id = db_manager.get_media_id(media_path)
        if media_id is None:
            # We use the modification time as a simple form of hash for now
            media_id = db_manager.insert_media_file(media_path, str(mod_time), int(mod_time))
        
        if media_id is not None:
            subtitles = subtitle_parser.parse_subtitle_file(subtitle_path)
            db_manager.insert_subtitles(media_id, subtitles)
            print(f"  Successfully loaded {len(subtitles)} subtitles.")

def query_subtitles(query_str, before_lines, after_lines):
    """Performs a global search on the database and handles EDL generation."""
    conn = db_manager.connect_db()
    cursor = conn.cursor()
    
    search_pattern = f"%{query_str}%"
    
    cursor.execute('''
        SELECT T1.file_path, T2.start_time, T2.end_time, T2.id, T1.id
        FROM media_files AS T1
        JOIN subtitles AS T2 ON T1.id = T2.media_id
        WHERE T2.text LIKE ?
        ORDER BY T1.file_path, T2.start_time
    ''', (search_pattern,))
    
    results = cursor.fetchall()
    
    edl_output = []
    
    if not results:
        print(f"No results found for '{query_str}'")
        return
        
    print(f"Found {len(results)} matches for '{query_str}'")
    
    for row in results:
        file_path, start_time, end_time, sub_id, media_id = row

        # Handle --before
        if before_lines > 0:
            cursor.execute('''
                SELECT start_time
                FROM subtitles
                WHERE media_id = ? AND id < ?
                ORDER BY id DESC
                LIMIT ?
            ''', (media_id, sub_id, before_lines))
            before_subs = cursor.fetchall()
            if before_subs:
                start_time = before_subs[-1][0]
        
        # Handle --after
        if after_lines > 0:
            cursor.execute('''
                SELECT end_time
                FROM subtitles
                WHERE media_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
            ''', (media_id, sub_id, after_lines))
            after_subs = cursor.fetchall()
            if after_subs:
                end_time = after_subs[-1][0]
        
        length = convert_time_to_seconds(start_time, end_time)
        edl_output.append((file_path, start_time, length))

    conn.close()
    
    write_edl_file(edl_output, query_str)


def main():
    parser = argparse.ArgumentParser(description="Search media subtitles and generate mpv EDL files.")
    parser.add_argument('directory', nargs='?', help='Root directory to scan for media and subtitles. Required for --reload and --update. Not needed for --query.')
    parser.add_argument('--reload', action='store_true', help='Recreate the database from scratch.')
    parser.add_argument('--update', action='store_true', help='Only update new or modified files.')
    parser.add_argument('--query', dest='query_str', help='Text to search for in subtitles.')
    parser.add_argument('--before', type=int, default=1, help='Number of subtitle entries to include before the match.')
    parser.add_argument('--after', type=int, default=1, help='Number of subtitle entries to include after the match.')
    
    args = parser.parse_args()

    # Determine action based on flags
    if args.reload or args.update:
        if not args.directory:
            print("Error: --reload and --update flags require a directory argument.")
            parser.print_help()
            exit(1)
        load_subtitles(args.directory, reload=args.reload)
    elif args.query_str:
        query_subtitles(args.query_str, args.before, args.after)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()