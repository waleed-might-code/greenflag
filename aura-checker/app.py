from flask import Flask, render_template, request, jsonify
from groq import Groq
from dotenv import load_dotenv
import os
import base64
from PIL import Image
import io

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def resize_image(image_data):
    img = Image.open(io.BytesIO(image_data))
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGB')
    max_size = 1024
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=85)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'selfie' not in request.files:
            return jsonify({'error': 'Selfie is required'}), 400
        
        selfie = request.files['selfie']
        if selfie.filename == '':
            return jsonify({'error': 'No selfie selected'}), 400
        
        selfie_b64 = resize_image(selfie.read())
        
        music_input = request.form.get('music_link', '').strip()
        music_screenshot = request.files.get('music_screenshot')
        
        if not music_input and not music_screenshot:
            return jsonify({'error': 'Please provide either a Spotify link or screenshot'}), 400
        
        # Analyze selfie
        selfie_response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": "Analyze this selfie. Describe the person's vibe, energy, aesthetic, and overall aura in 2-3 sentences. Be specific about facial expression, style, and the feeling they project."
                }, {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{selfie_b64}"}
                }]
            }],
            temperature=0.8,
            max_tokens=300
        )
        
        selfie_vibe = selfie_response.choices[0].message.content
        
        # Analyze music
        if music_screenshot and music_screenshot.filename:
            music_b64 = resize_image(music_screenshot.read())
            music_response = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": "Analyze this Spotify screenshot. Describe the music taste, vibe, and energy of the songs/artists shown. What does this music say about the person? Be specific."
                    }, {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{music_b64}"}
                    }]
                }],
                temperature=0.8,
                max_tokens=300
            )
            music_vibe = music_response.choices[0].message.content
        else:
            music_response = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{
                    "role": "user",
                    "content": f"Based on this Spotify link or description: {music_input}\n\nDescribe the music taste, vibe, and energy. What does this music say about the person? Be specific."
                }],
                temperature=0.8,
                max_tokens=300
            )
            music_vibe = music_response.choices[0].message.content
        
        # Combine analysis
        final_response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": f"""You are an aura analyst. Based on these two analyses, provide a complete aura reading:

FACE VIBE: {selfie_vibe}

MUSIC VIBE: {music_vibe}

Provide your analysis in EXACTLY this format:

AURA_SCORE: [number from 1-100]
AURA_ARCHETYPE: [one powerful archetype name, 2-3 words max]
FACE_MUSIC_MATCH: [percentage 1-100 of how well their face vibe matches their music vibe]
VIBE_WORDS: [exactly 5 powerful single words separated by commas that capture their combined aura]
VERDICT: [one cinematic, poetic sentence that captures their entire essence]

Be bold, specific, and insightful. The verdict should feel like a movie tagline about them."""
            }],
            temperature=0.9,
            max_tokens=400
        )
        
        result_text = final_response.choices[0].message.content
        
        # Parse the response
        result = {}
        for line in result_text.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower().replace('_', '')
                result[key] = value.strip()
        
        return jsonify({
            'aura_score': result.get('aurascore', 'N/A'),
            'aura_archetype': result.get('auraarchetype', 'N/A'),
            'face_music_match': result.get('facemusicmatch', 'N/A'),
            'vibe_words': result.get('vibewords', 'N/A'),
            'verdict': result.get('verdict', 'N/A')
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
