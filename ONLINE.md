# Putting the Forgetful Fish website online

**Status:** running from this PC behind a Cloudflare tunnel (section 4). No other
host is chosen. Two decisions are yours:

1. **Where it runs.** The options are below, with their trade-offs.
2. **Who may get in.** Set `MTG_BOT_INVITE_CODE` so people need an account
   (section 2b). Without it the site is open to anyone who can reach it.

## 1. Check it on this PC first

Run `serve-website-prod.cmd` in `C:\Users\stasjo\mtg-bot`. It starts the
production server on <http://127.0.0.1:5003>. This is the same server,
settings and feedback code the online version uses. Feedback goes to
`feedback-prod-test` next to the launcher, not to your real feedback folder.

`start-website.cmd` (port 5002) is still the development server.

## 2. Settings

The server reads these environment variables. Empty values count as unset.

| Variable | What it does | Default |
|---|---|---|
| `MTG_BOT_HOST` | Address to listen on. The Docker image uses `0.0.0.0`. | `127.0.0.1` |
| `PORT` (or `MTG_BOT_PORT`) | Port. | `5002` |
| `MTG_BOT_CARD_POOL` | Card pool. Keep `fish`. | `fish` |
| `MTG_BOT_FEEDBACK_DIR` | Where Feedback reports and `REVIEW_LIST.md` are written. Use a folder that survives restarts. | `feedback/` in the working folder |
| `MTG_BOT_REPLAYS_ROOT` | Folder the replay list reads. | `replays/` in the working folder |
| `MTG_BOT_SECRET_KEY` | Flask secret key, which signs the log-in cookies. Set a long random value so log-ins survive restarts. | random per start |
| `MTG_BOT_INVITE_CODE` | When set, the site has accounts (section 2b) and every page needs a log-in. The code people type to register. | unset (no accounts) |
| `MTG_BOT_ACCOUNTS_FILE` | The accounts file. Put it on the `/data` volume. | `accounts/accounts.json` in the working folder |
| `MTG_BOT_ACCESS_PASSWORD` | Without accounts: every page asks for this password (any user name). Ignored when `MTG_BOT_INVITE_CODE` is set. | unset (open) |

The health check is `/healthz`. It never asks for the password or a log-in.

### 2b. Accounts

With `MTG_BOT_INVITE_CODE` set:

- Every page and API route needs a log-in. Visitors land on `/login`.
- People create an account at `/register` with a user name (3-24 letters,
  digits, `_` or `-`), a password (8-200 characters) and the invite code. You
  give them the invite code yourself; it is the only way to register.
- Passwords are stored only as salted scrypt hashes. The accounts file also
  holds user names and creation times, so keep it out of git.
- A log-in lasts 30 days. `/logout` ends it.
- Limits, in memory and reset on restart: 8 failed log-ins for one user name
  within 15 minutes lock that name for the rest of the window; 20 wrong invite
  codes within 15 minutes stop all registrations for the same window.
- There is no password reset and no e-mail. To remove an account, stop the
  server, delete its entry in the accounts file, and start the server again.
  The person can then register again with the same user name.

## 3. Run it with Docker

Build the image on a machine with Docker (the Dockerfile is in this folder):

```bash
docker build -t fish-website .
```

Run it. Keep the `/data` volume: feedback and replays live there.

```bash
docker run -d --restart unless-stopped -p 8080:8080 \
  -v fish-data:/data \
  -e MTG_BOT_SECRET_KEY="a-long-random-value" \
  -e MTG_BOT_INVITE_CODE="the-invite-code-for-your-friends" \
  -e MTG_BOT_ACCOUNTS_FILE=/data/accounts.json \
  fish-website
```

Run **one** container. Games live in the server's memory, so a second copy
would not see the first one's games.

## 4. Where to host it

| Option | Cost | Good for | Trade-offs |
|---|---|---|---|
| **Home PC behind a tunnel** (Cloudflare Tunnel or Tailscale Funnel) | Free | Playtesting with a few people now | Your PC must stay on (`keep-pc-awake.ps1`). Your home connection carries the traffic. Feedback stays on your disk. |
| **Small VPS** (Hetzner, DigitalOcean, Lightsail) with Docker and Caddy for HTTPS | Low monthly cost; check current pricing | Always-on, without your PC | You run the server: updates, firewall, SSH. Feedback is on the server's disk, so copy it down to review. |
| **Managed container platform** (Fly.io, Render, Railway) | Low monthly cost | Easy deploys | Feedback needs a paid persistent volume; free tiers sleep or lose the disk. |
| **Serverless** (Cloud Run, Lambda) | Pay per use | Not for this site | Games live in memory and there is no disk. Needs a redesign. |

Measured on this PC with the Fish pool: the server uses about 100 MB after
start and about 130 MB after one full game. Games kept in memory add more,
so choose at least 1 GB. We have not tested several games at once.

## 5. HTTPS

Log-ins send the password (and the invite code, at registration) with every
request. Only run the site behind HTTPS, with `MTG_BOT_INVITE_CODE` or
`MTG_BOT_ACCESS_PASSWORD`. A VPS with Caddy gets HTTPS
automatically; a tunnel provides it too. Plain HTTP on the internet would
expose the password.

## 6. Reading feedback

Each Feedback report is a folder in the feedback volume, and every report adds
an unchecked line to `REVIEW_LIST.md`. Copy the folder and the file to your PC
(for a VPS, use `scp` or your host's file download). Claude acts only on items
you tick `[x]` in your copy of `REVIEW_LIST.md`.

## 7. Updating

Pull the new commit, rebuild the image, and restart the container. The `/data`
volume keeps feedback and replays across restarts.

**Always restart after an update, even without rebuilding.** The server keeps
the HTML pages it rendered when it started, but it reads the JavaScript and CSS
from disk on every request. After a `git merge` or `git pull` on a running
server, the page and the script can come from different versions and the Play
tab can stop responding. On the home PC: stop the server's Python process and
start it again with the same command as before. The Cloudflare tunnel can keep
running; its address does not change when only the server restarts.

## 8. Known limits

- **One process only.** Games live in memory.
- **Feedback can fill the disk.** Each report is capped (6 images of 5 MB,
  20,000 characters), but there is no total cap and no rate limit.
- **Card images come from Scryfall** at run time, so the host needs outbound
  internet.
- **Accounts are local.** The accounts file is the only store: no password
  reset, no e-mail, no admin screen.

## What is verified

- The production server ran on this PC from a clean venv built only from
  `requirements-web.txt`. `/healthz` answered, a feedback report was saved and
  added to `REVIEW_LIST.md`, and a full replay game was served.
- The web app does not load torch. `tests/test_web_server.py` checks this.
- Accounts: `tests/test_accounts.py` (registration, log-in, invite code,
  throttles, failed saves) and `tests/test_web_server_accounts.py` (the log-in
  gate, the log-in, register and log-out pages).
- **Not verified yet:** `docker build` (Docker is not installed on this PC).
  Build it on a machine with Docker before you rely on it.
