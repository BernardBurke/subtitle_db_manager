#!/usr/bin/env python3

import sys
import os
import tempfile
import subprocess
from collections import Counter

def stitch_edl_segments(edl_filepath):
    """
    Reads an mpv EDL file, checks for a single unique input file,
    and uses ffmpeg's concat demuxer to stitch the segments via stream copy.
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
                
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue

                # Expected format: /path/file.mp4,1395,13
                try:
                    parts = line.split(',')
                    if len(parts) != 3:
                        raise ValueError("Incorrect number of fields.")

                    path = parts[0].strip()
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
        for p in unique_paths:
            print(f"- {p}", file=sys.stderr)
        return

    input_file = unique_paths[0]
    output_filename = f"stitched_{os.path.basename(input_file)}"
    output_filepath = os.path.join(tempfile.gettempdir(), output_filename)
    
    # --- 3. Generate FFmpeg Concat Input File ---
    
    print(f"🔍 Input Source: {input_file}")
    
    # Create the FFmpeg concat demuxer input file in /tmp/
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tf:
        ffmpeg_input_path = tf.name
        print(f"📝 Generating temporary FFmpeg input file: {ffmpeg_input_path}")
        
        # FFmpeg concat demuxer format requires repeating the 'file' directive
        # followed by 'inpoint' and 'outpoint' for each segment.
        for record in edl_records:
            # We must use quotes for the file path in case it contains spaces
            tf.write(f"file '{record['path']}'\n")
            tf.write(f"inpoint {record['start']}\n")
            tf.write(f"outpoint {record['end']}\n")

    # --- 4. Run FFmpeg ---
    
    print(f"🚀 Running FFmpeg. Output will be saved to: {output_filepath}")

    # FFmpeg command structure:
    # -f concat: Use the concat demuxer
    # -safe 0: Allows absolute/complex paths in the input list
    # -i: The list of segments we generated
    # -c copy: Use stream copy (no re-encoding needed!)
    # -map 0:v -map 0:a -map 0:s?: Map video, audio, AND **all subtitle streams**
    # -y: Overwrite output if it exists
    ffmpeg_cmd = [
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', ffmpeg_input_path,
        '-c', 'copy',
        # Map all streams: video, audio, and **optional subtitles**
        '-map', '0:v', 
        '-map', '0:a', 
        '-map', '0:s?', # The '?' makes the subtitle stream optional
        '-y',
        output_filepath
    ]

    # Execute the command
    try:
        # Use subprocess.run for better handling and output
        result = subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
        print("\n✅ Success! Stitched video saved to:")
        print(output_filepath)
        
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
