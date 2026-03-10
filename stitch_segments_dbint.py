#!/usr/bin/env python3

import sys
import os
import tempfile
import subprocess
import sqlite3
from typing import List, Dict, Any

# ====================================================================
# CONFIGURATION: MUST BE UPDATED
# ====================================================================
# You MUST replace this with the actual path to your subtitle database file
DB_PATH = os.path.expanduser('~/path/to/your/subtitles.db') 
# You MUST replace this with the name of your subtitle table
SUBTITLES_TABLE = 'subtitle_entries' 
# ====================================================================

# --- Database Interaction ---

def query_subtitle_db(file_path: str, start_sec: float, end_sec: float) -> List[Dict]:
    """
    Queries the database for subtitle entries linked to the media file 
    that **overlap** with the given time range [start_sec, end_sec].
    """
    results = []
    normalized_path = os.path.abspath(file_path)

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # BROAD OVERLAP QUERY: 
        # Subtitle ends *after* segment starts AND subtitle starts *before* segment ends.
        query = f"""
        SELECT text, start_time, end_time
        FROM {SUBTITLES_TABLE}
        WHERE file_path = ? 
          AND end_time > ?      
          AND start_time < ?    
        ORDER BY start_time ASC;
        """
        
        cursor.execute(query, (normalized_path, start_sec, end_sec))
        
        for row in cursor.fetchall():
            results.append({
                'text': row['text'],
                'start': row['start_time'],  # Original start
                'end': row['end_time']      # Original end
            })

    except sqlite3.Error as e:
        print(f"❌ Database Error when querying: {e}", file=sys.stderr)
        print(f"   Check DB_PATH: '{DB_PATH}' and SUBTITLES_TABLE: '{SUBTITLES_TABLE}'.", file=sys.stderr)
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}", file=sys.stderr)
    finally:
        if 'conn' in locals() and conn:
            conn.close()

    return results

# --- Subtitle Reconstruction Logic ---

def format_time_to_srt(seconds: float) -> str:
    """Converts a float of seconds into the SRT time format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    # Ensure milliseconds are correct by handling floating point precision
    millis = int((seconds - int(seconds)) * 1000 + 0.5) 
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def reconstruct_subtitles(edl_records: List[Dict], output_srt_path: str):
    """
    Generates a new SRT file with correct timing based on EDL segments,
    trimming any subtitles that cross the segment boundaries.
    """
    
    print(f"\n📝 Reconstructing Subtitles to: {output_srt_path}")
    
    stitched_time = 0.0  # Tracks the cumulative length (S_start)
    srt_index = 1        

    with open(output_srt_path, 'w', encoding='utf-8') as srt_file:
        for record in edl_records:
            R_start = record['start'] # Original segment start
            R_end = record['end']     # Original segment end
            
            # Use the broad query to get all overlapping subtitles
            subtitle_entries = query_subtitle_db(record['path'], R_start, R_end) 

            for entry in subtitle_entries:
                T_original_start = entry['start']
                T_original_end = entry['end']
                
                # --- APPLY TRIMMING LOGIC ---
                
                # 1. Determine the actual start time within the segment
                Actual_Start_Time_Original = max(T_original_start, R_start)
                
                # 2. Determine the actual end time within the segment
                Actual_End_Time_Original = min(T_original_end, R_end)

                # Skip if the trimming resulted in an empty or negative duration
                if Actual_End_Time_Original <= Actual_Start_Time_Original:
                    continue

                # Calculate the new start time (S_start + offset from R_start)
                new_start_sec = stitched_time + (Actual_Start_Time_Original - R_start)
                
                # Calculate the new end time
                new_end_sec = stitched_time + (Actual_End_Time_Original - R_start)

                # Write the new SRT block
                new_start_srt = format_time_to_srt(new_start_sec)
                new_end_srt = format_time_to_srt(new_end_sec)
                
                srt_file.write(f"{srt_index}\n")
                srt_file.write(f"{new_start_srt} --> {new_end_srt}\n")
                srt_file.write(f"{entry['text']}\n\n")
                
                srt_index += 1

            # Update the cumulative stitched time for the next segment
            stitched_time += record['length']
            
    print("✅ Subtitle reconstruction complete. Subtitles are now accurately timed.")

# --- Main Stitching Logic ---

def stitch_edl_segments(edl_filepath: str):
    """
    Reads an mpv EDL file, checks for a single unique input file,
    uses ffmpeg's concat demuxer to stitch the segments via stream copy,
    and reconstructs the subtitle track.
    """
    
    print(f"🎬 Processing EDL file: {edl_filepath}")

    if not os.path.exists(edl_filepath):
        print(f"❌ Error: EDL file not found at {edl_filepath}", file=sys.stderr)
        return

    # --- 1. Read and Parse EDL Lines ---
    
    file_paths = []
    edl_records = []
    
    try:
        with open(edl_filepath, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'): continue

                try:
                    parts = line.split(',')
                    if len(parts) != 3: raise ValueError("Incorrect number of fields.")

                    path = parts[0].strip()
                    # Use float() for time to handle non-integer segments correctly
                    start = float(parts[1].strip())
                    length = float(parts[2].strip())
                    
                    file_paths.append(path)
                    edl_records.append({
                        'path': path,
                        'start': start,
                        'length': length,
                        'end': start + length # Calculate end time
                    })
                
                except ValueError as e:
                    print(f"⚠️ Warning: Skipping invalid line {line_num}: '{line}'. Details: {e}", file=sys.stderr)
                    
    except IOError as e:
        print(f"❌ Error reading EDL file: {e}", file=sys.stderr)
        return

    if not edl_records:
        print("ℹ️ No valid segments found in the EDL file. Exiting.")
        return

    # --- 2. Check for Unique File Path ---
    
    unique_paths = list(set(file_paths))

    if len(unique_paths) != 1:
        print("❌ Error: EDL file must contain exactly **one** unique file path.", file=sys.stderr)
        print(f"Found {len(unique_paths)} unique path(s):", file=sys.stderr)
        for p in unique_paths: print(f"- {p}", file=sys.stderr)
        return

    input_file = unique_paths[0]
    output_filename = f"stitched_{os.path.basename(input_file)}"
    # Output to /tmp/ as requested
    output_filepath = os.path.join(tempfile.gettempdir(), output_filename) 
    
    # --- 3. Generate FFmpeg Concat Input File ---
    
    print(f"🔍 Input Source: {input_file}")
    
    # Create the FFmpeg concat demuxer input file in /tmp/
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tf:
        ffmpeg_input_path = tf.name
        print(f"📝 Generating temporary FFmpeg input file: {ffmpeg_input_path}")
        
        for record in edl_records:
            # Use single quotes around the path to handle spaces safely
            tf.write(f"file '{record['path']}'\n") 
            tf.write(f"inpoint {record['start']}\n")
            tf.write(f"outpoint {record['end']}\n")

    # --- 4. Run FFmpeg ---
    
    print(f"🚀 Running FFmpeg. Output will be saved to: {output_filepath}")

    ffmpeg_cmd = [
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', ffmpeg_input_path,
        '-c', 'copy',
        '-map', '0:v', 
        '-map', '0:a', 
        '-y',
        output_filepath
    ]

    try:
        # Execute the command
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
        
        # --- 5. Reconstruct Subtitles (Only if FFmpeg succeeds) ---
        
        # Determine the path for the new SRT file
        srt_filepath = output_filepath.replace(os.path.splitext(output_filepath)[1], ".srt")
        
        # Call the subtitle reconstruction function
        reconstruct_subtitles(edl_records, srt_filepath)
        
        print("\n✅ Success! Stitched video saved to:")
        print(output_filepath)
        print(f"Accurately timed subtitles saved to: {srt_filepath}")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ FFmpeg failed with exit code {e.returncode}", file=sys.stderr)
        print("--- FFmpeg STDERR ---", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        print("---------------------", file=sys.stderr)
        
    except FileNotFoundError:
        print("❌ Error: The 'ffmpeg' command was not found. Please ensure it is installed and in your PATH.", file=sys.stderr)
        
    finally:
        # Clean up the temporary FFmpeg input file
        os.remove(ffmpeg_input_path)
        print(f"🧹 Cleaned up temporary file: {ffmpeg_input_path}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 stitch_segments.py <path/to/mpv.edl>", file=sys.stderr)
        sys.exit(1)
        
    stitch_edl_segments(sys.argv[1])