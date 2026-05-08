from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import urllib3

# Disable insecure request warnings if necessary (tnresults sometimes has SSL issues)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://tnresults.nic.in/rdopex.htm",
    "Origin": "https://tnresults.nic.in",
    "Content-Type": "application/x-www-form-urlencoded"
}

@app.route('/api/scrape', methods=['POST'])
def scrape():
    data = request.json
    regno = data.get('regno')
    dob = data.get('dob')

    if not regno or not dob:
        return jsonify({"success": False, "error": "Missing regno or dob"}), 400

    url = "https://tnresults.nic.in/rdopex.asp"
    payload = {
        "regno": regno,
        "dob": dob,
        "B1": "Get Marks"
    }

    try:
        # verify=False is used because government sites sometimes have certificate issues
        response = requests.post(url, data=payload, headers=HEADERS, verify=False, timeout=10)
        
        if response.status_code != 200:
             return jsonify({"success": False, "error": f"External server returned {response.status_code}"}), 502

        soup = BeautifulSoup(response.text, 'html.parser')

        # Basic validation: Check for "Invalid Register Number" text
        if "Invalid Register Number" in response.text:
            return jsonify({"success": False, "error": "Invalid Register Number"}), 200

        # Refined Parsing Logic based on Browser Inspection
        # The main results are usually in a <div class="design"> or similar
        # We look for the table that contains "NAME" or "Register No"
        
        extracted_info = {
            "NAME": None,
            "REGNO": regno,
            "DOB": dob,
            "TOTAL": None,
            "RESULT": None,
            "SUBJECTS": {}
        }
        
        tables = soup.find_all('table')
        
        target_table = None
        for table in tables:
            text_content = table.get_text()
            if "Example" in text_content: # Skip instructions table if any
                continue
            if "NAME" in text_content or "REGISTER NUMBER" in text_content or "Register No" in text_content:
                target_table = table
                break
        
        if not target_table:
             # Fallback: Try the div class 'design' which usually holds the result
             design_div = soup.find('div', class_='design')
             if design_div:
                 target_table = design_div.find('table')

        if target_table:
            rows = target_table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                row_text = row.get_text(separator=' ', strip=True)
                row_text_upper = row_text.upper()

                # Reliable Name Parsing: Look for the text containing the Register Number
                if str(regno) in row_text:
                    clean_text = row_text.replace(str(regno), '').replace('(', '').replace(')', '').replace('-', '').strip()
                    clean_text = clean_text.replace("Registration Number", "").replace("Reg No", "").strip()
                    if len(clean_text) > 2 and not extracted_info['NAME']:
                         extracted_info['NAME'] = clean_text

                if not cols: 
                    continue
                
                # Check for Name Row (fallback)
                if "NAME" in row_text_upper and ":" in row_text_upper and not extracted_info['NAME']:
                    parts = row_text_upper.split(':')
                    if len(parts) > 1:
                        extracted_info['NAME'] = parts[1].strip()

                # Extract Marks / Status
                if "TOTAL" in row_text_upper:
                    for col in cols:
                        if col.text.strip().isdigit(): 
                            extracted_info['TOTAL'] = col.text.strip()
                    for col in cols:
                        if col.text.strip().upper() in ['PASS', 'FAIL']:
                            extracted_info['RESULT'] = col.text.strip().upper()

                # Subject-Wise Marks parsing
                # If row has >=3 columns (Subject | ... | Total | Pass/Fail)
                if len(cols) >= 3 and "SUBJECT" not in row_text_upper and "TOTAL" not in row_text_upper:
                    subject_name = cols[0].text.strip()
                    
                    # Heuristic: the marks are usually near the end
                    # Typical structure: Subject Name | Theory | Internal | Practical | Total | Result
                    # We want the Total column (usually 2nd to last)
                    
                    # Basic cleanup for subject name (remove codes like '001 LANGUAGE')
                    # Keep it simple for now, usually the first column IS the subject
                    
                    if subject_name:
                        # Find the mark value (Total for that subject)
                        # We generally assume the 2nd to last column is the subject total
                        # But let's look for the first valid large integer or specific column index
                        
                        subject_total = cols[-2].text.strip()
                        subject_result = cols[-1].text.strip()
                        
                        # Validate if it looks like a mark row
                        if subject_total.isdigit() or subject_total == "ABS": # Handle Absent
                             extracted_info['SUBJECTS'][subject_name] = subject_total

        # Fallback Name extraction (Header row)
        if not extracted_info['NAME'] and target_table:
             first_row = target_table.find('tr')
             if first_row:
                 text = first_row.get_text(separator=' ', strip=True)
                 if "(" in text and ")" in text:
                     parts = text.split('(')
                     if len(parts) > 0 and len(parts[0]) > 2:
                         extracted_info['NAME'] = parts[0].strip()


        # Check if we found meaningful data
        if not extracted_info['NAME'] and not extracted_info['SUBJECTS']:
             # Fallback: Just return successful connection but no data found
             return jsonify({
                 "success": False, 
                 "error": "Data not found or format changed",
                 "raw_preview": response.text[:200]
             }), 200

        return jsonify({
            "success": True,
            "data": extracted_info
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# Vercel requires this for the WSGI application
if __name__ == '__main__':
    app.run(debug=True)
