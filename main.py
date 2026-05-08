import httpx
import json
import os
import io
import qrcode
import img2pdf
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, Form, Response, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont

# Custom Utils
from encryption_utils import encrypt_key, decrypt_key

app = FastAPI(title="Bambuddy Inventory Manager")

# --- CONFIGURATION & PATHS ---

DATA_DIR = "data"
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LABEL_SETTINGS_FILE = 'label_settings.json'
TEMPLATES_FILE = "label_templates.json"

# Setup Template Engine
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(CURRENT_DIR, "templates"))


# --- CORE UTILITY FUNCTIONS ---

def load_app_config() -> Dict[str, Any]:
    """Loads the Bambuddy URL and API token from the local config file."""
    if not os.path.exists(CONFIG_PATH):
        raise HTTPException(status_code=404, detail="Configuration file missing. Please run setup.")
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


async def forward_to_bambuddy(method: str, path: str, json_data: Optional[Dict] = None) -> Any:
    """
    Unified helper to forward requests to the Bambuddy API.
    Handles authentication, URL construction, and plural/singular path fallbacks.
    """
    config = load_app_config()
    base_url = config["url"].rstrip("/")
    token = decrypt_key(config["api_token"])

    target_url = f"{base_url}{path}"
    headers = {
        "X-API-Key": token,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=method,
                url=target_url,
                headers=headers,
                json=json_data,
                timeout=10.0
            )

            # Handle API variations (plural vs singular)
            if response.status_code == 405 and "/spools/" in path:
                alt_path = path.replace("/spools/", "/spool/")
                return await forward_to_bambuddy(method, alt_path, json_data)

            if response.status_code in [200, 201, 204]:
                return response.json() if response.status_code != 204 else {"status": "success"}

            raise HTTPException(status_code=response.status_code, detail=response.text)

        except httpx.RequestError as exc:
            raise HTTPException(status_code=500, detail=f"Bambuddy connection error: {exc}")


# --- WEB UI ROUTES (Function names matched to templates) ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Renders the main dashboard."""
    spools = []
    error_message = None
    try:
        spools = await forward_to_bambuddy("GET", "/api/v1/inventory/spools")
    except Exception as e:
        error_message = str(e)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"spools": spools, "error": error_message}
    )


@app.get("/spool/{spool_id}", response_class=HTMLResponse)
async def get_spool_detail(request: Request, spool_id: int):
    """Renders the detail view for a specific spool."""
    try:
        spool_data = await forward_to_bambuddy("GET", f"/api/v1/inventory/spools/{spool_id}")
        return templates.TemplateResponse(
            request=request,
            name="spool_detail.html",
            context={"spool": spool_data}
        )
    except Exception:
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context={"message": "Spool not found"}
        )


@app.get("/credentials", response_class=HTMLResponse)
async def credentials(request: Request):
    """Settings page for API credentials."""
    current_url = ""
    token_exists = False
    if os.path.exists(CONFIG_PATH):
        try:
            data = load_app_config()
            current_url = data.get("url", "")
            token_exists = bool(data.get("api_token"))
        except:
            pass

    return templates.TemplateResponse(
        request=request,
        name="credentials.html",
        context={"current_url": current_url, "token_exists": token_exists}
    )


# --- CONFIGURATION ACTIONS ---

@app.post("/save-config")
async def action_save_config(bambuddy_url: str = Form(...), api_token: str = Form(...)):
    """Saves the encrypted API configuration."""
    try:
        encrypted_token = encrypt_key(api_token)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump({"url": bambuddy_url, "api_token": encrypted_token}, f, indent=4)

        return HTMLResponse(content="""
            <div class="p-4 mt-4 text-sm border rounded-xl bg-green-500/10 border-green-500/30 text-green-400">
                <p class="font-bold text-white">Config Saved Successfully</p>
            </div>
        """)
    except Exception as e:
        return HTMLResponse(content=f"❌ Error: {str(e)}", status_code=500)


# --- PROXY API ROUTES ---

@app.post("/api/v1/inventory/spools")
async def api_create_spool(data: Dict):
    return await forward_to_bambuddy("POST", "/api/v1/inventory/spools", data)


@app.patch("/api/v1/inventory/spools/{spool_id}")
async def api_patch_spool(spool_id: int, data: Dict):
    return await forward_to_bambuddy("PATCH", f"/api/v1/inventory/spools/{spool_id}", data)


@app.delete("/api/v1/inventory/spools/{spool_id}")
async def api_delete_spool(spool_id: int):
    return await forward_to_bambuddy("DELETE", f"/api/v1/inventory/spools/{spool_id}")


# --- LABEL DESIGNER & EXPORT ---

@app.get("/spool/{spool_id}/label", response_class=HTMLResponse)
async def label_designer(request: Request, spool_id: int):
    """Renders the label designer interface."""
    try:
        spool_data = await forward_to_bambuddy("GET", f"/api/v1/inventory/spools/{spool_id}")
    except:
        spool_data = {"id": spool_id, "brand": "Unknown", "material": "Error"}

    return templates.TemplateResponse(
        request=request,
        name="label_designer.html",
        context={"spool": spool_data}
    )


@app.get("/api/label-config")
async def api_get_label_config():
    if os.path.exists(LABEL_SETTINGS_FILE):
        with open(LABEL_SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {"elements": None}


@app.post("/api/label-config")
async def api_save_label_config(request: Request):
    config_data = await request.json()
    with open(LABEL_SETTINGS_FILE, 'w') as f:
        json.dump(config_data, f, indent=4)
    return {"status": "success"}


@app.get("/api/label-export/{spool_id}")
async def api_export_label(spool_id: int, request: Request, format: str = "png"):
    """Generates the label based on saved layout."""
    try:
        if not os.path.exists(LABEL_SETTINGS_FILE):
            return JSONResponse({"error": "No layout found"}, status_code=404)

        with open(LABEL_SETTINGS_FILE, 'r') as f:
            config = json.load(f)

        spool_data = await forward_to_bambuddy("GET", f"/api/v1/inventory/spools/{spool_id}")

        # Scaling and Dimensions
        raw_w = min(max(float(config.get('width', 60)), 10), 300)
        raw_h = min(max(float(config.get('height', 30)), 10), 300)
        scale = 10
        img = Image.new('L', (int(raw_w * scale), int(raw_h * scale)), color=255)
        draw = ImageDraw.Draw(img)

        field_mapping = {
            "id": f"#{spool_id}",
            "brand": str(spool_data.get("brand", "")),
            "material": str(spool_data.get("material", "")),
            "subtype": str(spool_data.get("material_subtype", "")),
            "color": str(spool_data.get("color_name", ""))
        }

        # Elements
        for key, el in config.get('elements', {}).items():
            if not el.get('show') or key == 'qr': continue
            text_str = field_mapping.get(key, "")
            if not text_str or text_str == "None": continue

            f_size = int(float(el.get('size', 3)) * scale)
            font = None
            for path in ["arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
                try:
                    font = ImageFont.truetype(path, f_size)
                    break
                except:
                    continue

            draw.text((int(float(el.get('x', 0)) * scale), int(float(el.get('y', 0)) * scale)),
                      text_str, fill=0, font=font or ImageFont.load_default())

        # QR Code
        qr_conf = config.get('elements', {}).get('qr', {})
        if qr_conf.get('show'):
            qr = qrcode.QRCode(box_size=1, border=0)
            # Link back to the local detail page
            qr.add_data(f"{str(request.base_url).rstrip('/')}/spool/{spool_id}")
            qr.make(fit=True)
            qr_img = qr.make_image().convert('L')
            q_size = int(float(qr_conf.get('size', 15)) * scale)
            qr_img = qr_img.resize((q_size, q_size), Image.Resampling.NEAREST)
            img.paste(qr_img, (int(float(qr_conf.get('x', 40)) * scale), int(float(qr_conf.get('y', 5)) * scale)))

        img_io = io.BytesIO()
        img.save(img_io, format='PNG', optimize=True)
        img_bytes = img_io.getvalue()

        if format.lower() == "pdf":
            pdf_bytes = img2pdf.convert(img_bytes)
            return Response(content=pdf_bytes, media_type="application/pdf")

        return Response(content=img_bytes, media_type="image/png")

    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


# --- TEMPLATE STORAGE ---

@app.get("/api/labels/templates")
def api_get_templates():
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}


@app.post("/api/labels/templates/{name}")
async def api_save_template(name: str, request: Request):
    data = await request.json()
    templates_dict = api_get_templates()
    templates_dict[name] = data
    with open(TEMPLATES_FILE, 'w') as f:
        json.dump(templates_dict, f, indent=4)
    return {"status": "success"}


@app.delete("/api/labels/templates/{name}")
def api_delete_template(name: str):
    if os.path.exists(TEMPLATES_FILE):
        templates_dict = api_get_templates()
        if name in templates_dict:
            del templates_dict[name]
            with open(TEMPLATES_FILE, 'w') as f:
                json.dump(templates_dict, f, indent=4)
            return {"status": "success"}
    return {"status": "error", "message": "Template not found"}