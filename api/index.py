from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import os
import re

app = Flask(__name__)
CORS(app) 

DOWNLOAD_PATH = os.getcwd() 

def clean_youtube_url(url):
    base_url = re.sub(r'(\?.*)|(&.*)', '', url)
    return base_url

# --- get_format_list function remains the same (Correct logic) ---
def get_format_list(info):
    formats = info.get('formats', [])
    video_qualities = {}
    audio_qualities = []
    res_order = [2160, 1440, 1080, 720, 480, 360] 
    
    for f in formats:
        resolution = f.get('height')
        if resolution and resolution in res_order and f.get('vcodec') != 'none' and f.get('acodec') == 'none' and f.get('ext') == 'mp4':
            if resolution not in video_qualities:
                 video_qualities[resolution] = {
                    'format_name': f'{resolution}p MP4',
                    'format_code': f'bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]', 
                    'resolution': f'{resolution}p'
                }

    final_video_list = []
    for res in res_order:
        if res in video_qualities:
            final_video_list.append(video_qualities[res])

    audio_formats = sorted([f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none' and f.get('asr')], 
                           key=lambda x: x.get('abr', 0), reverse=True)

    seen_bitrates = set()
    for f in audio_formats:
        abr = f.get('abr')
        ext = f.get('ext')
        
        if abr and abr not in seen_bitrates and (ext == 'm4a' or ext == 'webm'):
            quality_tag = f'{abr}kbps ({ext.upper()})'
            if len(audio_qualities) == 0:
                 quality_tag = f'Highest Quality ({abr}kbps {ext.upper()})'

            audio_qualities.append({
                'format_name': quality_tag,
                'format_code': f'{f.get("format_id")}',
                'resolution': quality_tag,
                'ext': ext.upper(),
                'abr': abr
            })
            seen_bitrates.add(abr)

    if audio_qualities:
        base_format_code = audio_qualities[0]['format_code']
        
        audio_qualities.append({
            'format_name': '8D Surround Sound (FFmpeg)',
            'format_code': base_format_code, 
            'resolution': '8D Audio',
            'ext': 'MP3',
            'abr': 320
        })

    audio_qualities.reverse() 
    
    return final_video_list, audio_qualities

@app.route('/get_formats', methods=['POST'])
def get_formats():
    """Video metadata aur available download formats laata hai."""
    # (Unchanged)
    try:
        data = request.json
        video_url = data.get('url')
        if not video_url:
            return jsonify({"status": "error", "message": "Koi URL nahi mili."}), 400

        cleaned_url = clean_youtube_url(video_url)
        
        ydl_opts_meta = {'quiet': True, 'simulate': True, 'listformats': True}
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(cleaned_url, download=False)
            if 'entries' in info:
                info = info['entries'][0]
                
            video_title = info.get('title', 'Unknown Title')
            video_list, audio_list = get_format_list(info)
            
            if not video_list and not audio_list:
                return jsonify({"status": "error", "message": "Is video ke liye koi download format nahi mila."}), 404

            return jsonify({
                "status": "success",
                "title": video_title,
                "duration": info.get('duration_string', 'N/A'),
                "views": info.get('view_count', 0),
                "channel": info.get('uploader', 'Unknown'),
                "thumbnail": info.get('thumbnail'),
                "video_formats": video_list,
                "audio_formats": audio_list
            })

    except Exception as e:
        print(f"Format Extraction ERROR (yt-dlp): {e}")
        error_message = f"Format nikalne mein masla hua. Wajah: {str(e)}. Kripya 'pip install --upgrade yt-dlp' chala kar dobara koshish karein."
        return jsonify({"status": "error", "message": error_message}), 500


@app.route('/download_specific', methods=['POST'])
def download_video_specific():
    """Chune hue format mein video download karta hai."""
    try:
        data = request.json
        video_url = data.get('url')
        format_code = data.get('format_code')
        video_title = data.get('title')
        format_name = data.get('format_name')

        if not video_url or not format_code:
            return jsonify({"status": "error", "message": "URL ya Format Code nahi mila."}), 400

        cleaned_url = clean_youtube_url(video_url)
        
        print(f"\n--- Starting Download for: {video_title} ({format_name}) ---")
        
        safe_title = re.sub(r'[\\/:*?"<>|]', '', video_title)
        
        needs_merging = '+' in format_code
        is_8d_audio = '8D Surround Sound' in format_name

        postprocessors = []
        out_ext = '%(ext)s' 

        if needs_merging:
            # Video + Audio merging
            postprocessors.append({
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            })
            out_ext = 'mp4'
            
        elif is_8d_audio:
            # 8D Audio Conversion Filter (FFmpeg - Audio Post-Processing)
            
            # Step 1: Best audio nikal kar MP3 mein convert karein
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320', 
            })
            
            # Step 2: FFmpeg Filter (8D Effect) lagaein
            # **FIX:** yt-dlp ke latest versions mein FFmpegPostProcessor key kaam karti hai.
            # Agar phir bhi masla ho to 'key' mein 'PostProcessor' ya 'FFmpegPostProcessor' use karein.
            postprocessors.append({
                'key': 'FFmpegPostProcessor',
                'args': [
                    '-af', 
                    'aresample=44100,channelsplit=channel_layout=stereo:channels=FL|FR,apulsator=hz=0.08:volume=1:offset=0.25,loudnorm'
                ],
            })
            out_ext = 'mp3'
        
        ydl_opts = {
            'format': format_code,
            'outtmpl': os.path.join(DOWNLOAD_PATH, f'{safe_title} - {format_name}.{out_ext}'),
            'quiet': False, 
            'postprocessors': postprocessors,
            'merge_output_format': 'mp4' if needs_merging else None,
            # FFmpeg path ko explicit batana (Agar system path mein masla ho)
            #'ffmpeg_location': '/path/to/your/ffmpeg' # Uncomment and set path if needed
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([cleaned_url])

        return jsonify({
            "status": "success",
            "title": video_title,
            "format": format_name,
            "message": "Download successful!"
        })

    except Exception as e:
        print(f"Download ERROR (yt-dlp): {e}")
        # Error message ko update kiya gaya
        error_message = f"Download mein masla hua. Wajah: {str(e)}. Kripya 1) **FFmpeg** install/verify karein, aur 2) 'pip install --upgrade yt-dlp' zaroor chalaein."
        return jsonify({
            "status": "error", 
            "message": error_message
        }), 500

if __name__ == '__main__':
    print("------------------------------------------------------------------------")
    print("PYTHON DOWNLOAD SERVER READY (FFmpeg PostProcessor Key Fix)")
    print(f"Server is running on: http://127.0.0.1:5000/")
    print("------------------------------------------------------------------------")
    app.run(host='127.0.0.1', port=5000)