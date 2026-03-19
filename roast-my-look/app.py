import os
import base64
from io import BytesIO
from flask import Flask, render_template, request, jsonify
from groq import Groq
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def resize_image(image_file):
    img = Image.open(image_file)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGB')
    
    max_size = 1024
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    
    buffer = BytesIO()
    img.save(buffer, format='JPEG', quality=85)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image uploaded'}), 400
        
        image = request.files['image']
        if image.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        b64_image = resize_image(image)
        
        prompt = """Roast this person's look! Be brutally honest but funny. Analyze their outfit, style, and overall appearance.

Provide your roast in the following format:
1. ROAST LEVEL: Rate from 1-10 (10 = nuclear roast)
2. OVERALL VERDICT: One savage sentence summary
3. OUTFIT BREAKDOWN: Roast each piece of clothing/accessory
4. STYLE CRIMES: List the fashion violations
5. REDEMPTION TIP: One piece of actual advice
6. CLOSING BURN: End with your best one-liner roast

Be creative, funny, and savage but not mean-spirited."""

        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
                ]
            }],
            temperature=0.8,
            max_tokens=1000
        )
        
        roast = response.choices[0].message.content
        
        return jsonify({
            'success': True,
            'roast': roast
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
