#!/usr/bin/env python3
"""Small authenticated proxy in front of local ComfyUI.

Expose this proxy with ngrok instead of exposing ComfyUI directly.
Render should call this proxy and send Authorization: Bearer <COMFY_PROXY_TOKEN>.
"""
import os
from urllib.parse import urlencode

import requests
from flask import Flask, Response, jsonify, request


COMFY_LOCAL_URL = os.environ.get("COMFY_LOCAL_URL", "http://127.0.0.1:8188").rstrip("/")
PROXY_TOKEN = os.environ.get("COMFY_PROXY_TOKEN", "")
PROXY_PORT = int(os.environ.get("COMFY_PROXY_PORT", "8190"))
MAX_IMAGE_MB = int(os.environ.get("MAX_IMAGE_MB", "10"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_MB * 1024 * 1024


def check_auth():
    if not PROXY_TOKEN:
        return False
    expected = f"Bearer {PROXY_TOKEN}"
    return request.headers.get("Authorization") == expected


@app.before_request
def require_token():
    if request.path == "/health":
        return None
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401
    return None


def forward_response(resp):
    excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
    return Response(resp.content, status=resp.status_code, headers=headers)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "proxy": "comfyui"})


@app.get("/system_stats")
def system_stats():
    resp = requests.get(f"{COMFY_LOCAL_URL}/system_stats", timeout=15)
    return forward_response(resp)


@app.get("/queue")
def queue():
    resp = requests.get(f"{COMFY_LOCAL_URL}/queue", timeout=15)
    return forward_response(resp)


@app.get("/history")
def history():
    resp = requests.get(f"{COMFY_LOCAL_URL}/history", timeout=15)
    return forward_response(resp)


@app.get("/view")
def view():
    query = urlencode(request.args, doseq=True)
    resp = requests.get(f"{COMFY_LOCAL_URL}/view?{query}", timeout=60)
    return forward_response(resp)


@app.post("/prompt")
def prompt():
    resp = requests.post(f"{COMFY_LOCAL_URL}/prompt", json=request.get_json(), timeout=30)
    return forward_response(resp)


@app.post("/upload/image")
def upload_image():
    if "image" not in request.files:
        return jsonify({"error": "missing image"}), 400
    img = request.files["image"]
    files = {"image": (img.filename, img.stream, img.content_type)}
    data = {
        "type": request.form.get("type", "input"),
        "overwrite": request.form.get("overwrite", "true"),
    }
    resp = requests.post(f"{COMFY_LOCAL_URL}/upload/image", files=files, data=data, timeout=60)
    return forward_response(resp)


if __name__ == "__main__":
    if not PROXY_TOKEN:
        raise SystemExit("COMFY_PROXY_TOKEN is required")
    app.run(host="127.0.0.1", port=PROXY_PORT, debug=False)
