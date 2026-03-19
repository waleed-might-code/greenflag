from flask import Flask, render_template, request, jsonify
from groq import Groq
from dotenv import load_dotenv
import os
import base64
from PIL import Image
import io

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def resize_image(image_data):
    """Resize image to max 1024px while maintaining aspect ratio"""
    img = Image.open(io.BytesIO(image_data))
    
    # Convert RGBA to RGB if necessary
    if img.mode == 'RGBA':
        img = img.convert('RGB')
    
    # Resize if needed
    max_size = 1024
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = tuple(int(dim * ratio) for dim in img.size)
        img = img.resize(new_size, Image.Resampling.LANCZOS)
    
    # Convert to JPEG bytes
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=85)
    return buffer.getvalue()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        # Read and resize image
        image_data = file.read()
        resized_image = resize_image(image_data)
        b64_image = base64.b64encode(resized_image).decode('utf-8')
        
        # Call Groq vision API
        prompt = """Analyze this room photo and provide a savage roast with the following information:

1. ROOM_TYPE: What type of room is this? (bedroom, living room, office, etc.)
2. CLEANLINESS_SCORE: Rate cleanliness from 0-100
3. AESTHETIC_SCORE: Rate aesthetic/style from 0-100
4. ROAST: A hilarious, savage 2-3 sentence roast about the room's condition, decor choices, or vibe
5. COMPLIMENT: Find ONE genuine compliment about the room
6. SAVAGE_LINER: A brutal one-liner summary

Be funny, creative, and don't hold back on the roast!"""
        
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
                ]
            }],
            max_tokens=800,
            temperature=0.9
        )
        
        result_text = response.choices[0].message.content
        
        # Parse the response
        result = {
            'room_type': '',
            'cleanliness_score': '',
            'aesthetic_score': '',
            'roast': '',
            'compliment': '',
            'savage_liner': ''
        }
        
        lines = result_text.split('\n')
        current_field = None
        
        for line in lines:
            line = line.strip()
            if 'ROOM_TYPE' in line.upper():
                result['room_type'] = line.split(':', 1)[-1].strip()
            elif 'CLEANLINESS_SCORE' in line.upper() or 'CLEANLINESS' in line.upper():
                score = line.split(':', 1)[-1].strip()
                result['cleanliness_score'] = score
            elif 'AESTHETIC_SCORE' in line.upper() or 'AESTHETIC' in line.upper():
                score = line.split(':', 1)[-1].strip()
                result['aesthetic_score'] = score
            elif 'ROAST' in line.upper() and 'ROOM' not in line.upper():
                result['roast'] = line.split(':', 1)[-1].strip()
                current_field = 'roast'
            elif 'COMPLIMENT' in line.upper():
                result['compliment'] = line.split(':', 1)[-1].strip()
                current_field = 'compliment'
            elif 'SAVAGE_LINER' in line.upper() or 'SAVAGE' in line.upper():
                result['savage_liner'] = line.split(':', 1)[-1].strip()
                current_field = 'savage_liner'
            elif line and current_field and ':' not in line:
                result[current_field] += ' ' + line
        
        # Clean up results
        for key in result:
            result[key] = result[key].strip()
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=True)
