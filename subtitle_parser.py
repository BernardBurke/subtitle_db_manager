import pysrt
import re
from webvtt import WebVTT

def parse_srt(file_path):
    subs = pysrt.open(file_path, encoding='utf-8')
    subtitles_list = []
    for sub in subs:
        start_time = sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds + sub.start.milliseconds / 1000
        end_time = sub.end.hours * 3600 + sub.end.minutes * 60 + sub.end.seconds + sub.end.milliseconds / 1000
        text = sub.text.replace('\n', ' ')
        subtitles_list.append({'start_time': start_time, 'end_time': end_time, 'text': text})
    return subtitles_list

def parse_vtt(file_path):
    try:
        webvtt_parser = WebVTT()
        subs = webvtt_parser.read(file_path)
        subtitles_list = []
        for caption in subs:
            start_time = parse_vtt_timestamp(caption.start)
            end_time = parse_vtt_timestamp(caption.end)
            text = caption.text.replace('\n', ' ')
            subtitles_list.append({'start_time': start_time, 'end_time': end_time, 'text': text})
        return subtitles_list
    except Exception as e:
        print(f"Error parsing VTT file {file_path}: {e}")
        return []

def parse_vtt_timestamp(timestamp_str):
    parts = re.split(r'[:.]', timestamp_str)
    if len(parts) == 3: # 00:00.000 format
        minutes, seconds, milliseconds = map(int, parts)
        return minutes * 60 + seconds + milliseconds / 1000
    elif len(parts) == 4: # 00:00:00.000 format
        hours, minutes, seconds, milliseconds = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    return 0

def parse_subtitle_file(file_path):
    if file_path.endswith('.srt'):
        return parse_srt(file_path)
    elif file_path.endswith('.vtt'):
        return parse_vtt(file_path)
    return []