import os
from flask import Flask, render_template, request, jsonify
from groq import Groq
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
        data = request.get_json()
        question = data.get('question', '')
        
        if not question:
            return jsonify({'error': 'Please ask a question'}), 400
        
        prompt = f"""You are a mystical AI fortune teller with cosmic wisdom. Someone asks: "{question}"

Provide a fortune reading in the following format:
1. FORTUNE: Your mystical prediction (2-3 sentences)
2. LUCKY NUMBERS: 3 lucky numbers
3. LUCKY COLOR: One color that will bring fortune
4. ADVICE: One piece of mystical guidance
5. CRYSTAL BALL SAYS: A cryptic but intriguing final message

Be mystical, dramatic, and fun. Use cosmic/mystical language."""

        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=800
        )
        
        fortune = response.choices[0].message.content
        
        return jsonify({
            'success': True,
            'fortune': fortune
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
