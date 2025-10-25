import sys
import os
import argparse
import re
import shutil
from datetime import datetime

# --- Existing Modules (No change to how they are imported) ---
try:
    import db_manager
    import file_walker
    import subtitle_parser
except ImportError:
    print("FATAL: Cannot find db_manager.py, file_walker.py, or subtitle_parser.py.")
    sys.exit(1)

# --- New Modules for the 'cut' command ---
try:
    import sub_cutter
    from sub_cutter import (
        convert_timestamp_to_milliseconds, 
        format_ms_to_ffmpeg_time, 
        format_time_offset_filename,
        get_media_duration_ms, 
        shift_subtitles, 
        extract_media_segment, 
        convert_vtt_to_srt
    )
except ImportError:
    print("FATAL: Cannot find sub_cutter.py. Ensure it is in the project root.")
    sys.exit(1)


# --- Existing Helper Functions ---

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
    
    safe_query = re.sub(r'[^a-zA-Z0-9_]+', '_', query_str)
    edl_filename = f"{safe_query}.edl"
    edl_path = os.path.join('/tmp', edl_filename)
    
    with open(edl_path, 'w') as f:
        f.write("# mpv EDL v0\n")
        
        for result in search_results:
            file_path, start_time, length = result
            f.write(f"{file_path},{start_time:.2f},{length:.2f}\n")
    
    print(f"\nEDL file saved to: {edl_path}")

def write_text_file(text_results, query_str):
    """Writes the matched subtitles text to a file for review."""

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
            
            start_vtt = current_time + 0.5
            end_vtt = start_vtt + (end_time - start_time)
            
            f.write(f"{format_timestamp(start_vtt)} --> {format_timestamp(end_vtt)}\n")
            f.write(f"{text}\n\n")
            
            current_time = end_vtt + 0.5

    print(f"Combined VTT file saved to: {vtt_path}")

def load_subtitles(directory_path, reload=False):
    """Handles loading or updating the database with subtitles."""
    
    # Use the default database name from db_manager
    db_name = db_manager.DATABASE_NAME 
    
    if not reload and os.path.exists(db_name):
        # This is an update, so backup the database first.
        backup_dir = os.path.expanduser('~/Downloads')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"subtitles_backup_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_filename)
        shutil.copy2(db_name, backup_path)
        print(f"Database backed up to: {backup_path}")

    if reload:
        print("Recreating database...")
        if os.path.exists(db_name):
            os.remove(db_name)
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
        
        # Note: Your original logic used two mod_time values. Assuming mod_time is an int/float.
        try:
            mod_time = os.path.getmtime(media_path)
            media_id = db_manager.insert_media_file(media_path, str(mod_time), int(mod_time))
        except FileNotFoundError:
            print(f"  WARNING: Media file not found: {media_path}. Skipping.")
            continue
        
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
    # --- ARGUMENT PARSING SETUP ---
    parser = argparse.ArgumentParser(
        description="Subtitle Database Manager and Media Cutter.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # Use subparsers to define distinct commands (load, query, cut)
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. LOAD COMMAND (Replaces --reload / --update)
    load_parser = subparsers.add_parser(
        "load", 
        help="Scan a directory and populate or update the database."
    )
    load_parser.add_argument(
        "directory", 
        help="Root directory to scan for media and subtitles."
    )
    load_parser.add_argument(
        '--reload', 
        action='store_true', 
        help='Recreate the database from scratch (delete and rebuild).'
    )

    # 2. QUERY COMMAND (Replaces --query)
    query_parser = subparsers.add_parser(
        "query", 
        help="Search for text in subtitles and generate EDL/VTT outputs."
    )
    query_parser.add_argument(
        'query_str', 
        help='Text to search for in subtitles.'
    )
    query_parser.add_argument(
        '--before', 
        type=int, 
        default=1, 
        help='Number of subtitle entries to include before the match.'
    )
    query_parser.add_argument(
        '--after', 
        type=int, 
        default=1, 
        help='Number of subtitle entries to include after the match.'
    )
    
    # 3. CUT COMMAND (The new functionality)
    cut_parser = subparsers.add_parser(
        "cut", 
        help="Shift a subtitle file and extract the corresponding media segment using ffmpeg."
    )
    cut_parser.add_argument(
        "subtitle_file", 
        help="Input subtitle file (.srt or .vtt) to be processed."
    )
    cut_parser.add_argument(
        "time_offset", 
        help="Start time for the cut (and subtitle shift offset) in HH:MM:SS format (e.g., 00:01:30)"
    )
    cut_parser.add_argument(
        "-l", 
        "--media_length", 
        type=int, 
        help="Optional: Length of the media segment to cut, in seconds."
    )
    cut_parser.add_argument(
        "-m",
        "--media_file",
        help="Optional: Explicitly specify the related media file (skips auto-detection)."
    )
    
    args = parser.parse_args()

    # --- EXECUTION LOGIC ---
    
    if args.command == "load":
        load_subtitles(args.directory, reload=args.reload)
        
    elif args.command == "query":
        query_subtitles(args.query_str, args.before, args.after)

    elif args.command == "cut":
        # PERE Check
        if 'PERE' not in os.environ or not os.path.isdir(os.environ['PERE']):
            print("ERROR: PERE environment variable not set or directory does not exist.")
            sys.exit(1)
            
        output_directory = os.environ['PERE']
        input_subtitle_file = args.subtitle_file
        temp_srt_file = None

        # VTT Conversion Check
        if input_subtitle_file.lower().endswith('.vtt'):
            base_dir = os.path.dirname(input_subtitle_file)
            base_name = os.path.basename(os.path.splitext(input_subtitle_file)[0])
            temp_srt_file = os.path.join(base_dir, f".temp_{base_name}.srt")
            
            try:
                convert_vtt_to_srt(args.subtitle_file, temp_srt_file) # Use original file for conversion
                input_subtitle_file = temp_srt_file # Use temp file for shifting
            except RuntimeError as e:
                print(f"ERROR: VTT conversion failed: {e}")
                sys.exit(1)

        # Media File Location (Simplified local search)
        media_file = args.media_file
        if not media_file:
            base_path = os.path.splitext(input_subtitle_file)[0].replace(".temp_", "")
            media_extensions = [".mp3", ".m4a", ".mp4", ".mkv", ".avi", ".mov"] 
            for ext in media_extensions:
                candidate = base_path + ext
                if os.path.exists(candidate):
                    media_file = candidate
                    break
                    
        if media_file is None or not os.path.exists(media_file):
            print("ERROR: Could not find a related media file. Use '-m' to specify it.")
            sys.exit(1)
        
        # Time Calculations and Validation
        try:
            media_duration_ms = get_media_duration_ms(media_file)
            time_offset_ms = convert_timestamp_to_milliseconds(args.time_offset)
        except (ValueError, RuntimeError) as e:
            print(f"ERROR: {e}")
            if temp_srt_file and os.path.exists(temp_srt_file): os.remove(temp_srt_file)
            sys.exit(1)

        if time_offset_ms >= media_duration_ms:
            print("ERROR: Time offset is greater than or equal to the media duration.")
            sys.exit(1)

        cut_length_ms = None
        media_end_time_ms = media_duration_ms
        
        if args.media_length:
            cut_length_ms = args.media_length * 1000
            media_end_time_ms = time_offset_ms + cut_length_ms
            if media_end_time_ms > media_duration_ms:
                print(f"WARNING: Requested cut length ({args.media_length}s) exceeds media duration.")
                media_end_time_ms = media_duration_ms
                cut_length_ms = media_duration_ms - time_offset_ms

        media_start_time_str = format_ms_to_ffmpeg_time(time_offset_ms)
        media_end_time_str = format_ms_to_ffmpeg_time(media_end_time_ms)
        
        # Filename Generation
        time_offset_formatted = format_time_offset_filename(args.time_offset)
        cut_length_suffix = f"-cut{args.media_length}" if args.media_length else ""
        
        # Use the original, non-temp filename for output naming
        base_name = os.path.basename(os.path.splitext(args.subtitle_file)[0]) 
        media_ext = os.path.splitext(media_file)[1]
        sub_ext = ".srt" 
        
        media_output = os.path.join(
            output_directory, 
            f"{base_name}_{time_offset_formatted}{cut_length_suffix}{media_ext}"
        )
        output_srt_file = os.path.join(
            output_directory, 
            f"{base_name}_{time_offset_formatted}{cut_length_suffix}{sub_ext}"
        )
        
        # Summary and Execution
        print("\n--- Summary of Operation ---")
        print(f"Source Media: {media_file}")
        print(f"Source Subtitle: {args.subtitle_file} (Processing: {input_subtitle_file})")
        print(f"Shift Offset: {args.time_offset}")
        print(f"Extraction Range: {media_start_time_str} to {media_end_time_str}")
        print(f"Output Media: {media_output}")
        print(f"Output Subtitle: {output_srt_file}")
        
        # Execution
        try:
            shift_subtitles(input_subtitle_file, output_srt_file, time_offset_ms, cut_length_ms)
            print(f"Subtitle shifting complete: {output_srt_file}")

            extract_media_segment(media_file, media_start_time_str, media_end_time_str, media_output)
        except Exception as e:
            print(f"CRITICAL ERROR during execution: {e}")
            
        # Cleanup
        if temp_srt_file and os.path.exists(temp_srt_file):
            os.remove(temp_srt_file)
            print(f"Cleaned up temporary VTT conversion file: {temp_srt_file}")
        
        print("\n--- All operations complete ---")


if __name__ == "__main__":
    main()