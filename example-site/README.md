# MyATM Mod — Example Bank Website

This is a minimal Flask web application showing how to integrate with the
[MyATM Forge mod](https://github.com/your-repo/myatm-mod) for Minecraft 1.20.1.

## Setup

```bash
pip install -r requirements.txt
python app.py
```

## Configuration

1. In `app.py`, change:
   - `ATM_API_KEY` — must match the password in `config/myATM.cfg` on your server
   - `SECRET_KEY` — any random string for session security

2. In `config/myATM.cfg` on your Minecraft server:
   ```
   'YourBankName':'https://your-site.com':'Change-This-Password'
   ```

## Admin account

Register an account with the username `Admin` — it will have access to the admin panel at `/admin`.

## API endpoints used by the mod

| Endpoint | Called by |
|---|---|
| `POST /api/atm` | ATM block — generates/retrieves a card |
| `POST /api/terminal` | Terminal block — processes a payment |

See `app.py` for the full request/response format.
