# Green Flag Checker 🚩

AI-powered relationship health analyzer for WhatsApp chats. Upload your chat export and get instant insights into your relationship dynamics.

## Features

- 💚 **Green Flags**: Identify healthy communication patterns
- 🚨 **Red Flags**: Spot concerning behaviors that need attention
- 📊 **Health Score**: Get an overall relationship assessment (0-100)
- 💡 **Recommendations**: Receive personalized advice for improvement
- 🔒 **Privacy First**: Chats are analyzed securely and not stored permanently

## Live Demo

🌐 **[https://green-flag-checker.doless.work](https://green-flag-checker.doless.work)**

## How It Works

1. Export your WhatsApp chat (Settings → More → Export chat → Without media)
2. Upload the .zip file to the analyzer
3. Get instant AI-powered analysis of your relationship

## Tech Stack

- **Backend**: Flask (Python)
- **AI**: Groq API with Llama 3.3 70B
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **Deployment**: Systemd + Cloudflare Tunnel

## Local Setup

```bash
# Clone the repository
git clone https://github.com/waleed-might-code/greenflag.git
cd greenflag

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
echo "GROQ_API_KEY=your_api_key_here" > .env
echo "PORT=5030" >> .env

# Run the app
python3 app.py
```

Visit `http://localhost:5030` in your browser.

## Environment Variables

- `GROQ_API_KEY`: Your Groq API key (get one at [console.groq.com](https://console.groq.com))
- `PORT`: Port to run the server on (default: 5030)

## API Endpoints

- `GET /` - Main upload page
- `POST /analyze` - Upload and analyze chat
- `GET /result/<result_id>` - View analysis results
- `GET /health` - Health check endpoint

## Privacy & Security

- Chat files are temporarily stored during analysis
- Results are stored with random IDs
- No personal data is logged or shared
- Analysis uses only a sample of messages (max 200)

## License

MIT

## Author

Built with ❤️ for healthy relationships
