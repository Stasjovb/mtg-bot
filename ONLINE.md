# Putting the Forgetful Fish website online

**Status: nothing is deployed, and the site is not public.** Two decisions are
yours before it goes live:

1. **Where it runs.** The options are below, with their trade-offs.
2. **Public, or private behind a password.** Set `MTG_BOT_ACCESS_PASSWORD` to
   keep it private.

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
| `MTG_BOT_SECRET_KEY` | Flask secret key. Nothing uses sessions yet. Set a long random value. | random per start |
| `MTG_BOT_ACCESS_PASSWORD` | When set, every page asks for this password (any user name). When unset, anyone who can reach the site can use it. | unset (open) |

The health check is `/healthz`. It never asks for the password.

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
  -e MTG_BOT_ACCESS_PASSWORD="the-password-for-your-friends" \
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

Basic authentication sends the password with every request. Only use
`MTG_BOT_ACCESS_PASSWORD` behind HTTPS. A VPS with Caddy gets HTTPS
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

## 8. Known limits

- **One process only.** Games live in memory.
- **Feedback can fill the disk.** Each report is capped (6 images of 5 MB,
  20,000 characters), but there is no total cap and no rate limit.
- **Card images come from Scryfall** at run time, so the host needs outbound
  internet.
- **One shared password**, no accounts.

## What is verified

- The production server ran on this PC from a clean venv built only from
  `requirements-web.txt`. `/healthz` answered, a feedback report was saved and
  added to `REVIEW_LIST.md`, and a full replay game was served.
- The web app does not load torch. `tests/test_web_server.py` checks this.
- **Not verified yet:** `docker build` (Docker is not installed on this PC).
  Build it on a machine with Docker before you rely on it.
