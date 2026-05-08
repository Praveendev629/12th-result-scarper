from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import urllib3
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__, template_folder='../templates', static_folder='../static')
CORS(app)

FORM_URL = "https://tnresults.nic.in/2026_HSCtnresults/2026_9994hsc.asp"
REFERER  = "https://tnresults.nic.in/2026_HSCtnresults/2026_5341hsc.htm"

HEADERS = {
    "User-Agent"     : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer"        : REFERER,
    "Origin"         : "https://tnresults.nic.in",
    "Content-Type"   : "application/x-www-form-urlencoded",
    "Accept"         : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection"     : "keep-alive",
}


def parse_result_html(html: str, regno: str, dob: str):
    soup = BeautifulSoup(html, "html.parser")

    body_text = soup.get_text(separator=" ", strip=True)
    for phrase in ["invalid", "no record", "not found", "enter valid"]:
        if phrase in body_text.lower():
            return None, "Invalid register number or date of birth."

    tables = soup.find_all("table")
    result_table = None
    for tbl in tables:
        if tbl.find("td", string=re.compile(r"TOTAL", re.I)):
            result_table = tbl
            break
    if not result_table:
        return None, "Result table not found — server may be busy."

    rows = result_table.find_all("tr")
    if not rows:
        return None, "Result table is empty."

    # Name + regno from first row
    header_text = rows[0].get_text(separator=" ", strip=True)
    m = re.match(r"^(.*?)\s*\(\s*(\d+)\s*\)", header_text)
    student_name    = m.group(1).strip() if m else "Unknown"
    register_number = m.group(2).strip() if m else regno

    subjects      = {}
    total_marks   = None
    result_status = None

    for row in rows[2:]:
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cols) < 2:
            continue
        subject = cols[0].strip().upper()
        if not subject:
            continue

        if subject == "TOTAL":
            for c in reversed(cols):
                c = c.strip().lstrip("0") or "0"
                if c.isdigit():
                    total_marks = int(c)
                    break
            for c in cols:
                if c.strip().upper() in ("PASS", "FAIL"):
                    result_status = c.strip().upper()
                    break
            continue

        subject_total = None
        for c in reversed(cols[1:]):
            clean = c.strip().replace("\xa0", "").lstrip("0") or "0"
            if re.match(r"^\d+$", clean):
                subject_total = int(clean)
                break
        if subject_total is not None:
            subjects[subject] = subject_total

    # Return in the format the frontend expects (uppercase keys matching original site)
    return {
        "NAME"   : student_name,
        "REGNO"  : register_number,
        "DOB"    : dob,
        "TOTAL"  : total_marks,
        "RESULT" : result_status,
        "SUBJECTS": subjects,
    }, None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def scrape():
    payload = request.get_json(silent=True) or {}
    regno = payload.get("regno", "").strip()
    dob   = payload.get("dob", "").strip()

    if not regno or not dob:
        return jsonify({"success": False, "error": "regno and dob are required."}), 400

    try:
        resp = requests.post(
            FORM_URL,
            data={"regno": regno, "dob": dob, "B1": "Get Marks"},
            headers=HEADERS,
            verify=False,
            timeout=20,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Request timed out."}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "Cannot reach tnresults.nic.in."}), 502
    except requests.exceptions.HTTPError as e:
        return jsonify({"success": False, "error": f"HTTP error: {e}"}), 502
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    data, err = parse_result_html(resp.text, regno, dob)
    if err:
        return jsonify({"success": False, "error": err}), 404

    return jsonify({"success": True, "data": data})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
