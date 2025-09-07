import os

MEDIA_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.webm', '.m4a', '.mp3']

def find_media_and_subtitles(directory_path):
    media_files = []
    subtitle_files = {}

    for root, _, files in os.walk(directory_path):
        for file in files:
            file_path = os.path.join(root, file)
            file_name, file_ext = os.path.splitext(file)
            
            if file_ext.lower() in MEDIA_EXTENSIONS:
                media_files.append(file_path)
            elif file_ext.lower() in ['.srt', '.vtt']:
                # Store subtitle paths by their base name
                if file_name not in subtitle_files or file_ext.lower() == '.srt':
                    subtitle_files[file_name] = file_path

    # Pair media with subtitles
    file_pairs = []
    for media_path in media_files:
        media_name, _ = os.path.splitext(os.path.basename(media_path))
        if media_name in subtitle_files:
            file_pairs.append({
                'media_path': media_path,
                'subtitle_path': subtitle_files[media_name]
            })

    return file_pairs