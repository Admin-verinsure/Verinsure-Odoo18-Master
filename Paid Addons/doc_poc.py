import xmlrpc.client
import base64
import os
import sys

# --------- ODOO CONNECTION ----------
ODOO_URL = "http://223.165.66.206"
DB = "staging_not4profit"
USERNAME = "nikhil_rana@verinsure.online"
PASSWORD = "Nikhil@1945"  # API key recommended

# ✅ WORKING DMS DIRECTORY (under Insurance & Risk Management -> API Upload Test)
DMS_DIRECTORY_ID = 72

# --------- 3 FILES FROM YOUR LOCAL SYSTEM ----------
pdf_files = [
    r"C:\Users\Nikhil Rana\Downloads\Rotary_Oceania_Associations_GL_Liability_Multiguard_CoC_2025-2.pdf",
    r"C:\Users\Nikhil Rana\Downloads\INV_25-26_0013.pdf",
    r"C:\Users\Nikhil Rana\Downloads\INV_25-26_0012-1.pdf",
]

def die(msg):
    print("❌", msg)
    sys.exit(1)

# --------- AUTHENTICATE ----------
common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USERNAME, PASSWORD, {})
if not uid:
    die("Authentication failed. Check DB, user, API key/password, and URL.")

print(f"✅ Authenticated. UID = {uid}")
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

# --------- CHECK DMS MODELS EXIST ----------
has_dms = models.execute_kw(DB, uid, PASSWORD, "ir.model", "search",
                            [[("model", "=", "dms.file")]], {"limit": 1})
if not has_dms:
    die("dms.file model not found. DMS module not installed/enabled on this DB.")

# --------- VERIFY DIRECTORY EXISTS ----------
dir_ok = models.execute_kw(
    DB, uid, PASSWORD,
    "dms.directory", "search",
    [[("id", "=", DMS_DIRECTORY_ID)]],
    {"limit": 1}
)
if not dir_ok:
    die(f"DMS directory_id={DMS_DIRECTORY_ID} not found. Check it in Odoo.")

directory_id = DMS_DIRECTORY_ID
print(f"📁 Using DMS directory_id = {directory_id}")

# --------- UNIQUE NAME HANDLER ----------
def get_unique_name(filename: str) -> str:
    base, ext = os.path.splitext(filename)
    new_name = filename
    count = 1
    while True:
        existing = models.execute_kw(
            DB, uid, PASSWORD,
            "dms.file", "search",
            [[("name", "=", new_name), ("directory_id", "=", directory_id)]],
            {"limit": 1},
        )
        if not existing:
            return new_name
        new_name = f"{base}_{count}{ext}"
        count += 1

# --------- UPLOAD LOOP ----------
for path in pdf_files:
    if not os.path.exists(path):
        print(f"❌ File not found: {path}")
        continue

    filename = os.path.basename(path)
    unique_name = get_unique_name(filename)
    if unique_name != filename:
        print(f"⚠ Duplicate name: {filename} → renamed to {unique_name}")

    print(f"\n📄 Uploading: {unique_name}")

    with open(path, "rb") as f:
        data_b64 = base64.b64encode(f.read()).decode("utf-8")

    # 1) Create attachment
    attachment_id = models.execute_kw(
        DB, uid, PASSWORD,
        "ir.attachment", "create",
        [{
            "name": unique_name,
            "type": "binary",
            "datas": data_b64,
            "mimetype": "application/pdf",
        }]
    )
    print(f"   ✔ ir.attachment created: {attachment_id}")

    # 2) Create DMS file referencing attachment (NO permission_* fields)
    dms_vals = {
        "name": unique_name,
        "attachment_id": attachment_id,
        "directory_id": directory_id,
    }

    try:
        dms_file_id = models.execute_kw(DB, uid, PASSWORD, "dms.file", "create", [dms_vals])
        print(f"   ✔ dms.file created: {dms_file_id}")
    except xmlrpc.client.Fault as e:
        print(f"   ❌ dms.file create failed: {e}")
        # cleanup orphan attachment
        models.execute_kw(DB, uid, PASSWORD, "ir.attachment", "unlink", [[attachment_id]])
        print(f"   🧹 Deleted orphan attachment: {attachment_id}")
        continue

print("\n🎉 Done. Open DMS → Insurance & Risk Management → API Upload Test to see uploaded files.")
