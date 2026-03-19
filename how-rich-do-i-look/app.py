import os
import base64
from io import BytesIO
from flask import Flask, render_template, request, jsonify
from groq import Groq
from dotenv import load_dotenv
from PIL import Image
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def resize_image(image, max_size=1024):
    """Resize image to max dimension while maintaining aspect ratio"""
    width, height = image.size
    if width > max_size or height > max_size:
        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    return image

def image_to_base64(image):
    """Convert PIL Image to base64 string"""
    buffered = BytesIO()
    image.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

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
            return jsonify({'error': 'No file selected'}), 400
        
        # Open and process image
        image = Image.open(file.stream)
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Resize image
        image = resize_image(image)
        
        # Convert to base64
        image_b64 = image_to_base64(image)
        
        # Send to Groq vision
        prompt = """Analyze this image and provide an exaggerated, humorous fake wealth analysis based ONLY on visual cues.

Provide your analysis in the following format:
1. WEALTH TIER: (e.g., "Old Money Cosplay", "New Money Energy", "Broke But Make It Fashion", etc.)
2. FAKE NET WORTH: A ridiculous estimated range (e.g., "$2.3M - $4.7M" or "$847 - $1,200")
3. WHAT LOOKS RICH: List specific visual elements that scream wealth
4. WHAT LOOKS FAKE RICH: List things that expose the illusion
5. CLOSING LINE: A savage but funny one-liner roast

Be creative, entertaining, and brutally honest. Roast them with love."""

        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        }
                    }
                ]
            }],
            temperature=0.9,
            max_tokens=1000
        )
        
        analysis = response.choices[0].message.content
        
        return jsonify({'result': analysis})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
