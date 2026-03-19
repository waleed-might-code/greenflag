from flask import Flask, render_template, request, jsonify
from groq import Groq
from PIL import Image
import os
import io
import base64
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image uploaded'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        image = Image.open(file.stream)
        
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        
        max_size = 1024
        if max(image.size) > max_size:
            ratio = max_size / max(image.size)
            new_size = tuple(int(dim * ratio) for dim in image.size)
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=85)
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        prompt = """Analyze this fridge photo and provide a humorous life-state reading. Return EXACTLY these fields:

1. FRIDGE_PERSONALITY: A creative personality type (e.g., "The Chaotic Gourmet", "Minimalist Monk")
2. CHAOS_SCORE: A score from 0-100 (0=pristine discipline, 100=total chaos)
3. LIFE_READING: What this fridge reveals about the owner's life (2-3 sentences, witty)
4. PREDICTED_MEAL: One specific meal they'll likely make with what's in there
5. FORTUNE: A fortune-cookie style closing line

Be funny, observant, and slightly roast-y but affectionate."""

        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                ]
            }],
            max_tokens=800,
            temperature=0.9
        )
        
        result_text = response.choices[0].message.content
        
        return jsonify({
            'success': True,
            'result': result_text
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5006, debug=True)
