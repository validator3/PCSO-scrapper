# PCSO Lotto Scraper API

A Python Flask API that uses Playwright to scrape PCSO lotto results and return clean JSON for n8n.

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Check if API is running |
| `GET /results` | Get structured JSON with all game results |
| `GET /message` | Get pre-formatted message ready for Messenger/Telegram |

## Example Response from /message

```json
{
  "success": true,
  "message": "PCSO Results - June 24, 2026\n(9PM Draw)\n\n6/58 Ultra Lotto (Jun 23, 2026): 04-21-41-40-39-52 | ₱128,000,000.00\n..."
}
```

## Deploy to Railway

1. Push this folder to a GitHub repo
2. Go to railway.app → New Project → Deploy from GitHub
3. Select the repo → Railway auto-detects Dockerfile
4. Done! Your API URL will be like: https://pcso-scraper.up.railway.app

## Connect to n8n

In your n8n workflow, replace the Fetch PCSO Website node with:
- Method: GET
- URL: https://YOUR-RAILWAY-URL/message

Then in Parse Results code:
```javascript
const message = $input.first().json.message;
return [{ json: { message } }];
```

That's it — no more parsing needed!
