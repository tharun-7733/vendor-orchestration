import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


origin = os.environ.get("API_ORIGIN", "").strip().rstrip("/")
parsed_origin = urlsplit(origin)
if parsed_origin.scheme != "https" or not parsed_origin.netloc or parsed_origin.path:
    raise SystemExit("API_ORIGIN must be an HTTPS origin, for example https://api.example.com")

config_path = Path(__file__).resolve().parents[1] / "public" / "vercel.json"
config = json.loads(config_path.read_text())
for rewrite in config["rewrites"]:
    destination = urlsplit(rewrite["destination"])
    rewrite["destination"] = urlunsplit(
        (parsed_origin.scheme, parsed_origin.netloc, destination.path, destination.query, destination.fragment)
    )
config_path.write_text(json.dumps(config, indent=2) + "\n")
