import os
import re
import ffmpeg # The new dependency

# --- Time Conversion Functions ---

def time_str_to_ms(time_str: str) -> int:
    """Converts a time string (HH:MM:SS,mmm or HH:MM:SS) to total milliseconds."""
    # Use regex to safely split by ':', ',', or '.'
    time_parts = re.split(r"[:,\.]", time_str)
    
    # Handle cases where milliseconds might be missing or separated by comma/dot
    if len(time_parts) < 3:
        raise ValueError(f"Invalid time format in subtitle entry: {time_str}. Expected HH:MM:SS[,mmm]")

    h = int(time_parts[0])
    m = int(time_parts[1])
    s = int(time_parts[2])
    # Tries to get milliseconds (index 3), defaults to 0 if not present
    ms = int(time_parts[3]) if len(time_parts) > 3 else 0 
    
    return h * 3600000 + m * 60000 + s * 1000 + ms

def format_ms_to_srt(milliseconds: int) -> str:
    """Converts total milliseconds back into the SRT time format (HH:MM:SS,mmm)."""
    ms = int(milliseconds)
    total_seconds, ms = divmod(ms, 1000)
    total_minutes, s = divmod(total_seconds, 60)
    h, m = divmod(total_minutes, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}" # Note: COMMA separator

def format_ms_to_ffmpeg_time(milliseconds: int) -> str:
    """Converts total milliseconds into the format HH:MM:SS.mmm for ffmpeg/duration calculation."""
    ms = int(milliseconds)
    total_seconds, ms = divmod(ms, 1000)
    total_minutes, s = divmod(total_seconds, 60)
    h, m = divmod(total_minutes, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}" # Note: DOT separator

def convert_timestamp_to_milliseconds(timestamp_str: str) -> int:
    """Converts a pure HH:MM:SS timestamp string (no milliseconds) to milliseconds."""
    parts = timestamp_str.split(':')
    if len(parts) == 3:
        h, m, s = map(int, parts)
        return h * 3600000 + m * 60000 + s * 1000
    raise ValueError("Invalid timestamp format for offset. Use HH:MM:SS")

# --- Core Subtitle Logic ---

def shift_subtitles(input_file: str, output_file: str, time_offset_ms: int, cut_length_ms: int = None):
    """Shifts subtitle timings in an SRT file based on a millisecond offset."""
    
    with open(input_file, "r", encoding="utf-8") as f_in, open(output_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            if "-->" in line:
                start_time_str, end_time_str = line.strip().split(" --> ")

                try:
                    start_ms = time_str_to_ms(start_time_str)
                    end_ms = time_str_to_ms(end_time_str)
                except ValueError as e:
                    print(f"Skipping malformed time line: {line.strip()}. Error: {e}")
                    f_out.write(line)
                    continue

                # Apply time offset
                shifted_start = max(0, start_ms - time_offset_ms)
                shifted_end = max(0, end_ms - time_offset_ms)

                # Apply cut logic
                if cut_length_ms is not None:
                    if shifted_start >= cut_length_ms:
                        continue 
                    if shifted_end > cut_length_ms:
                        shifted_end = cut_length_ms

                # Convert back and write
                shifted_start_str = format_ms_to_srt(shifted_start)
                shifted_end_str = format_ms_to_srt(shifted_end)

                f_out.write(f"{shifted_start_str} --> {shifted_end_str}\n")
            else:
                f_out.write(line)

# --- Media File and Extraction Logic ---

def get_media_duration_ms(media_file: str) -> int:
    """Probes the media file and returns its duration in milliseconds."""
    try:
        media_file_info = ffmpeg.probe(media_file)
        duration_s = float(media_file_info['format']['duration'])
        return int(duration_s * 1000)
    except ffmpeg.Error as e:
        raise RuntimeError(f"FFmpeg probe failed for {media_file}.") from e
    except Exception as e:
        raise RuntimeError(f"Could not determine media duration for {media_file}. Error: {e}") from e

def extract_media_segment(input_file: str, start_time: str, end_time: str, output_file: str):
    """Extracts a segment of media using stream copy."""
    print(f"Extracting media segment from {start_time} to {end_time} to {output_file}...")
    
    try:
        # 'ss' before 'i' for fast seeking. 'to' for absolute end time.
        (
            ffmpeg
            .input(input_file, ss=start_time)
            .output(output_file, to=end_time, c='copy', loglevel='error')
            .run(overwrite_output=True)
        )
        print(f"Media segment extracted successfully (stream copy) to {output_file}")
    except ffmpeg.Error as e:
        print(f"Error extracting media segment:")
        print(f"FFmpeg command failed. Error output:\n{e.stderr.decode()}")
        # Cleanup in case of failure
        if os.path.exists(output_file) and os.stat(output_file).st_size == 0:
            os.remove(output_file)
            print(f"Removed empty file: {output_file}")
        raise
        
def convert_vtt_to_srt(input_file: str, output_file: str):
    """Converts a VTT file to SRT using ffmpeg."""
    print(f"Converting {input_file} to temporary {output_file}...")
    try:
        (
            ffmpeg
            .input(input_file)
            .output(output_file, loglevel='error')
            .run(overwrite_output=True)
        )
    except ffmpeg.Error as e:
        raise RuntimeError(f"Failed to convert VTT file.") from e

def format_time_offset_filename(time_offset_str: str) -> str:
    """Formats an HH:MM:SS string for use in a filename (e.g., 000130)."""
    h, m, s = time_offset_str.split(":")
    return f"{h}{m}{s}"