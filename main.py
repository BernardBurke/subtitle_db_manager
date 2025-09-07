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

def format_timestamp(seconds):
    """Converts a time in seconds to HH:MM:SS.mmm format for VTT."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining_seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remaining_seconds:06.3f}"

def write_edl_file(search_results, query_str):
    """Generates a string in mpv EDL format and writes to a file."""
    
    # Sanitize query string for a safe filename
    safe_query = re.sub(r'[^a-zA-Z0-9_]+', '_', query_str)
    edl_filename = f"{safe_query}.edl"
    edl_path = os.path.join('/tmp', edl_filename)
    
    with open(edl_path, 'w') as f:
        # Add the required EDL header
        f.write("# mpv EDL v0\n")
        
        for result in search_results:
            file_path, start_time, length = result
            # EDL format: file_path, start_time, length
            f.write(f"{file_path},{start_time:.2f},{length:.2f}\n")
    
    print(f"\nEDL file saved to: {edl_path}")

def write_text_file(text_results, query_str):
    """Writes the matched subtitles text to a file for review."""

    # Sanitize query string for a safe filename
    safe_query = re.sub(r'[^a-zA-Z0-9_]+', '_', query_str)
    text_filename = f"{safe_query}.txt"
    text_path = os.path.join('/tmp', text_filename)
    
    with open(text_path, 'w') as f:
        current_file = None
        for result in text_results:
            file_path, start_time, end_time, text = result
            if file_path != current_file:
                f.write(f"\n--- File: {file_path} ---\n")
                current_file = file_path
            
            f.write(f"[{start_time:.2f} --> {end_time:.2f}]\n")
            f.write(f"{text}\n")

    print(f"Subtitles text file saved to: {text_path}")

def write_vtt_file(text_results, query_str):
    """Writes a combined VTT file with a new, sequential timeline."""
    safe_query = re.sub(r'[^a-zA-Z0-9_]+', '_', query_str)
    vtt_filename = f"{safe_query}.vtt"
    vtt_path = os.path.join('/tmp', vtt_filename)
    
    with open(vtt_path, 'w') as f:
        f.write("WEBVTT\n\n")
        
        current_time = 0.0
        for result in text_results:
            file_path, start_time, end_time, text = result
            
            # The start and end times in the VTT file are relative to the EDL
            # We add a small delay to separate the chunks visually
            start_vtt = current_time + 0.5
            end_vtt = start_vtt + (end_time - start_time)
            
            f.write(f"{format_timestamp(start_vtt)} --> {format_timestamp(end_vtt)}\n")
            f.write(f"{text}\n\n")
            
            current_time = end_vtt + 0.5

    print(f"Combined VTT file saved to: {vtt_path}")

def load_subtitles(directory_path, reload=False):
    """Handles loading or updating the database with subtitles."""
    if reload:
        print("Recreating database...")
        if os.path.exists(db_manager.DATABASE_NAME):
            os.remove(db_manager.DATABASE_NAME)
        db_manager.create_tables()
    
    file_pairs = file_walker.find_media_and_subtitles(directory_path)
    print(f"Found {len(file_pairs)} media/subtitle pairs.")

    processed_count = 0
    for pair in file_pairs:
        media_path = pair['media_path']
        subtitle_path = pair['subtitle_path']
        
        if not reload:
            media_id = db_manager.get_media_id(media_path)
            if media_id is not None:
                print(f"Skipping {media_path} (already in the database).")
                continue

        print(f"Processing {media_path}...")
        
        mod_time = os.path.getmtime(media_path)
        media_id = db_manager.insert_media_file(media_path, str(mod_time), int(mod_time))
        
        if media_id is not None:
            subtitles = subtitle_parser.parse_subtitle_file(subtitle_path)
            db_manager.insert_subtitles(media_id, subtitles)
            processed_count += 1
            print(f"  Successfully loaded {len(subtitles)} subtitles.")

    print(f"Loaded {processed_count} new media files.")


def query_subtitles(query_str, before_lines, after_lines):
    """Performs a global search on the database and handles EDL generation."""
    conn = db_manager.connect_db()
    cursor = conn.cursor()
    
    search_pattern = f"%{query_str}%"
    
    cursor.execute('''
        SELECT T1.file_path, T2.start_time, T2.end_time, T2.id, T1.id, T2.text
        FROM media_files AS T1
        JOIN subtitles AS T2 ON T1.id = T2.media_id
        WHERE T2.text LIKE ?
        ORDER BY T1.file_path, T2.start_time
    ''', (search_pattern,))
    
    results = cursor.fetchall()
    
    edl_entries = []
    text_entries = []
    
    if not results:
        print(f"No results found for '{query_str}'")
        return
        
    print(f"Found {len(results)} matches for '{query_str}'")
    
    for row in results:
        file_path, start_time_match, end_time_match, sub_id_match, media_id_match, text_match = row

        # Skip files that contain a comma in the filename
        if ',' in file_path:
            print(f"Skipping file with comma in name: {file_path}")
            continue

        # Get 'before' subtitles
        before_subs = []
        if before_lines > 0:
            cursor.execute('''
                SELECT start_time, end_time, text
                FROM subtitles
                WHERE media_id = ? AND id < ?
                ORDER BY id DESC
                LIMIT ?
            ''', (media_id_match, sub_id_match, before_lines))
            before_subs = list(reversed(cursor.fetchall()))

        # Get 'after' subtitles
        after_subs = []
        if after_lines > 0:
            cursor.execute('''
                SELECT start_time, end_time, text
                FROM subtitles
                WHERE media_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
            ''', (media_id_match, sub_id_match, after_lines))
            after_subs = cursor.fetchall()

        # Build the EDL and text entries
        edl_start_time = before_subs[0][0] if before_subs else start_time_match
        edl_end_time = after_subs[-1][1] if after_subs else end_time_match
        
        edl_length = convert_time_to_seconds(edl_start_time, edl_end_time)
        edl_entries.append((file_path, edl_start_time, edl_length))
        
        # Add all subtitles in the clip to the text entries
        for sub in before_subs:
            text_entries.append((file_path, sub[0], sub[1], sub[2]))
        text_entries.append((file_path, start_time_match, end_time_match, text_match))
        for sub in after_subs:
            text_entries.append((file_path, sub[0], sub[1], sub[2]))

    conn.close()
    
    write_edl_file(edl_entries, query_str)
    write_text_file(text_entries, query_str)
    write_vtt_file(text_entries, query_str)


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