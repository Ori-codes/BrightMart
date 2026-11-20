# BrightMart Traders – Inventory & Sales Management System (web interface)

Same system as the Tkinter version, but the screens are built with **HTML and CSS** and served by a small
**Flask** app. It runs on the shop computer and is opened in a browser – **no internet or cloud needed**.

## Run it
```
pip install flask
python app.py --demo       # sample data;  use  python app.py  for an empty system
```
Open **http://127.0.0.1:5000** in a browser.
To let a manager tablet on the shop Wi-Fi connect, run `python app.py --network` and open
`http://<shop-computer-ip>:5000` on the tablet (trusted networks only).

### Default logins
| Role | Username | Password |
|------|----------|----------|
| Store Manager | manager | manager123 |
| Sales Staff | sales | sales123 |
| Business Owner | owner | owner123 |

## Files
| Path | What it is |
|------|-----------|
| `app.py` | Flask routes (replaces `gui.py`) |
| `templates/*.html` | One HTML page per screen (`base.html` holds the shared header/nav) |
| `static/css/style.css` | All styling: blue + orange colours, light/dark themes, desktop/tablet/mobile layouts |
| `static/js/theme.js` | ~20 lines: remembers the light/dark choice |
| `static/img/logo.svg` | Hand-drawn blue basket logo with yellow lines |
| `models.py`, `security.py`, `database.py`, `auth.py`, `inventory.py`, `sales.py`, `reports.py` | Unchanged business logic and database code |
| `tests/` | 49 automated tests (32 logic + 17 web) – `python -m unittest discover -s tests -v` |

## Customising the look
Open `static/css/style.css`. The colours are all variables at the top (`--blue`, `--orange`, ...).
Change them once and every page updates. Dark-mode colours are in the `:root[data-theme="dark"]` block.

## Security notes
Passwords are hashed; every form carries a CSRF token; pages check the user's role on the server;
the session key is generated once into `secret.key` (do not upload it to GitHub – it is in `.gitignore`).

## Acknowledgement of AI use
Developed with the help of Claude (Anthropic) as a learning-support tool; the author reviewed and adapted the code.
