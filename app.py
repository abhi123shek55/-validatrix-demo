from flask import Flask, request, render_template, send_file
from lxml import etree as ET  # Using lxml for robust parsing
import pandas as pd
import io
import re
import base64
import json
import os
from flask import abort

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

@app.errorhandler(413)
def too_large(error):
    return render_template('upload.html', error='File/request too large. Maximum: 5 MB.'), 413

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.get('/sample')
def sample():
    return send_file(os.path.join(app.root_path, 'samples', 'demo_survey.xml'), as_attachment=True)


def strip_namespace(tag):
    if not isinstance(tag, str):
        return ''
    if '}' in tag:
        return tag.split('}', 1)[1].lower()
    else:
        return tag.lower()

# --- Upgraded XML Parser ---
def parse_questions_from_xml(content):
    import io as _io
    # Using lxml's parser which can recover from some errors
    if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError('DTD/entity declarations are not supported.')
    parser = ET.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)
    root = ET.fromstring(content, parser=parser)
    if root is None:
        raise ValueError('No XML document found.')
    errors = [e for e in parser.error_log if e.level_name in ('ERROR', 'FATAL') and e.domain_name != 'NAMESPACE']
    if errors:
        raise ValueError('Malformed XML. Please fix its structure before running validation.')
    question_tags = ("checkbox", "radio", "text", "textarea", "number")

    for elem in root.findall('.//*'):
        tag = strip_namespace(elem.tag)
        if tag in question_tags:
            # Extract rich data about child elements for complex rule checks
            children_data = []
            for child in elem:
                children_data.append({
                    "tag": strip_namespace(child.tag),
                    "attributes": {k.lower(): v for k, v in child.attrib.items()},
                    "text": (child.text or "").strip()
                })

            yield {
                "type": tag,
                "label": elem.get("label", "NO_LABEL"),
                "attributes": {k.lower(): v for k, v in elem.attrib.items()},
                "children": children_data
            }

# This function is no longer used but kept for historical context or future use.
def parse_questions_from_txt(content):
    lines = content.decode('utf-8', errors='ignore').splitlines()
    block_lines = []
    inside_block = False
    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(f"<{qt}") for qt in ("checkbox", "radio", "text", "textarea", "number")):
            inside_block = True
            block_lines = [stripped]
            if stripped.endswith(">"):
                inside_block = False
                block = ' '.join(block_lines)
                yield from _parse_txt_block(block)
        elif inside_block:
            block_lines.append(stripped)
            if stripped.endswith(">"):
                inside_block = False
                block = ' '.join(block_lines)
                yield from _parse_txt_block(block)

def _parse_txt_block(block):
    match_qtype = re.match(r"<(\w+)", block)
    if match_qtype:
        qtype = match_qtype.group(1).lower()
        if qtype in ("checkbox", "radio", "text", "textarea", "number"):
            attrs = {k.lower(): v for k, v in re.findall(r'([\w:]+)="([^"]*)"', block)}
            has_validate_tag = "<validate>" in block.lower()
            yield {
                "type": qtype,
                "label": attrs.get("label", "NO_LABEL"),
                "attributes": attrs,
                "has_validate_tag_txt": has_validate_tag,
                "children": [] # TXT parser does not support child elements yet
            }

# --- HELPER FUNCTIONS ---
def is_hidden(question):
    return "execute" in question.get("attributes", {}).get("where", "").lower()

# --- VALIDATION RULES WITH SIMPLIFIED MESSAGES ---

# Rule for Optional="1"
def check_optional_with_validate(question):
    # This rule should not apply to text/textarea, as they have a more specific rule
    if question['type'] in ('text', 'textarea'):
        return None

    if is_hidden(question) or question["attributes"].get("optional") != "1":
        return None

    if question['type'] == 'checkbox':
        attrs = question['attributes']
        for key in ('atleast', 'atmost', 'exactly'):
            if key in attrs:
                # Capitalize first word after emoji
                return f'⚠ Optional="1" present and {key} is also present, Double check this'

    has_validate = any(c['tag'] == 'validate' for c in question['children'])

    if has_validate:
        # Already capitalized
        return '⚠ Optional="1" present | <validate> tag present, Double check this'
    else:
        # Already capitalized
        return '❌ Optional="1" present | Validate tag missing'

# Rule for checkbox
def check_checkbox_conditions(question):
    if is_hidden(question):
        return None

    attrs = question["attributes"]
    has_validate = any(c['tag'] == 'validate' for c in question['children'])

    if attrs.get('atleast') == '0':
        if has_validate:
            # Capitalize first word after emoji
            return '⚠ Atleast="0" present | <validate> tag present, Double check this'
        else:
            # Capitalize first word after emoji
            return '❌ Atleast="0" present | <validate> tag missing'

    if attrs.get('exactly') == '0':
        # Capitalize first word after emoji
        return '❌ Exactly="0" present'

    if 'atleast' not in attrs and 'exactly' not in attrs:
        if has_validate:
            # Already capitalized
            return '⚠ Missing attribute "atleast" or "exactly", but <validate> tag is present. Double check this'
        else:
            if attrs.get('grouping') not in ('rows', 'cols'):
                 # Already capitalized
                 return '❌ Missing attribute "atleast" or "exactly" or <validate> tag'

    return None

# Rule for number
def check_number_optional_or_validate(question):
    if question["attributes"].get("optional") == "1":
        return None

    if is_hidden(question): return None

    attrs = question["attributes"]
    has_validate = any(c['tag'] == 'validate' for c in question['children'])

    if 'optional' not in attrs:
        if has_validate:
            # Capitalize first word after emoji
            return '⚠ "Optional" attribute is missing, Double check <validate> tag'
        else:
            # Capitalize first word after emoji
            return '❌ "Optional" attribute and validate tag both missing'

    if not (attrs.get('optional') == '0' or has_validate):
        # Already capitalized
        return '❌ Missing Optional="0" or validate tag'

    return None

# Rule for number range
def check_number_verify_range(question):
    if is_hidden(question): return None
    if 'verify' not in question["attributes"]:
        # Capitalize first word after emoji
        return '❌ Verify="range(x,y)" is missing'
    return None

# Rule for ss attributes
def check_ss_attributes(question):
    attrs = question["attributes"]
    if not any(k in attrs for k in ('ss:posttext', 'ss:pretext')):
        # Starts with technical term, no change
        return '❌ Missing "ss:posttext" or "ss:pretext" attribute'
    return None

# Rule for Text and Textarea Questions
def check_text_based_optional(question):
    # This function now handles all optionality for text/textarea, including Optional="1"
    if is_hidden(question):
        return None

    attrs = question.get("attributes", {})
    has_validate = any(c['tag'] == 'validate' for c in question['children'])

    # Primary Check: Optional="0" on the main question tag
    if attrs.get('optional') == '0':
        return None  # This is valid

    # Secondary Checks
    rows = [child for child in question['children'] if child['tag'] == 'row']

    # Case 1: Rows are present
    if rows:
        first_row_attrs = rows[0].get("attributes", {})
        # Check if first row is mandatory
        if first_row_attrs.get('optional') == '0':
            return None  # This is also valid

        # If first row is not mandatory, check for validate tag
        if has_validate:
            # Capitalize first word after emoji
            return '⚠ Optional="0" missing on question/first row | Double check <validate> tag'
        else:
            # Capitalize first word after emoji
            return '❌ Optional="0" missing on question/first row | <validate> tag missing'

    # Case 2: No rows are present
    else:
        if has_validate:
            # Capitalize first word after emoji
            return '⚠ Optional="0" missing | <validate> tag present, Double check this'
        else:
            # Capitalize first word after emoji
            return '❌ Optional="0" missing and no <validate> tag found'


# Rule for title content
def check_title_content(question):
    title = next((c for c in question['children'] if c['tag'] == 'title'), None)
    if title:
        # Check for various forms of "empty" content after XML parsing.
        invalid_content = (
            '\u00a0',  # Non-breaking space character (from &amp;nbsp;)
            'nbsp;',   # Literal string
            '&',       # Decoded ampersand (from &amp;)
            '&nbsp;',  # Literal string for partially decoded entities
            ''         # Empty or whitespace-only titles
        )
        if title['text'].lower() in invalid_content:
            # Already capitalized
            return '❌ Invalid title content'
    return None

# Rule for hidden cond
def check_hidden_cond(question):
    if is_hidden(question) and 'cond' in question["attributes"]:
        # Capitalize first word after emoji
        return '❌ "Cond" attribute found'
    return None

# Rule for hidden numeric verify
def check_hidden_numeric_verify(question):
    if is_hidden(question) and 'verify' in question["attributes"]:
        # Capitalize first word after emoji
        return '❌ "Verify" attribute found'
    return None

# Rule for hidden checkbox attributes
def check_hidden_checkbox_attrs(question):
    if is_hidden(question):
        attrs = question["attributes"]
        error_messages = []

        # Check for forbidden count attributes
        forbidden_attrs = ('atleast', 'exactly', 'atmost')
        for attr in forbidden_attrs:
            if attr in attrs:
                # Starts with variable attr name, no change needed in f-string itself
                error_messages.append(f"❌ '{attr}' present")

        # Check for forbidden Optional="0"
        if attrs.get('optional') == '0':
            # Capitalize first word after emoji
            error_messages.append('❌ Optional="0" present')

        if error_messages:
            return " | ".join(error_messages)

    return None

# Consolidated optional logic for hidden questions
def check_base_optional_logic(question):
    attrs = question.get("attributes", {})
    q_type = question["type"]
    if is_hidden(question):
        if q_type in ("number", "text", "textarea"):
            if attrs.get("optional") == "0":
                # Capitalize first word after emoji
                return '❌ Optional="0" found'
        elif q_type == "radio":
             if attrs.get("optional") != "1":
                # Capitalize first word after emoji
                return '❌ Optional="1" missing'
    return None

# --- RULESET ---
VALIDATION_RULES = {
    "radio":    [check_optional_with_validate, check_title_content, check_hidden_cond, check_base_optional_logic],
    "checkbox": [check_optional_with_validate, check_checkbox_conditions, check_title_content, check_hidden_cond, check_hidden_checkbox_attrs, check_base_optional_logic],
    "text":     [check_optional_with_validate, check_text_based_optional, check_title_content, check_hidden_cond, check_base_optional_logic],
    "textarea": [check_optional_with_validate, check_text_based_optional, check_title_content, check_hidden_cond, check_base_optional_logic],
    "number":   [check_optional_with_validate, check_number_optional_or_validate, check_number_verify_range, check_ss_attributes, check_title_content, check_hidden_cond, check_hidden_numeric_verify, check_base_optional_logic],
}

# --- Validation engine ---
def run_validations(questions):
    results = []
    for q in questions:
        question_label = q["label"]
        question_type_str = q["type"]

        if is_hidden(q):
            question_type_str = f"Hidden {question_type_str.capitalize()}"

        final_question_type = question_type_str.title()

        error_messages = []
        for rule in VALIDATION_RULES.get(q["type"], []):
            res = rule(q)
            if res:
                error_messages.append(res)

        if not error_messages:
            results.append({
                "Question Label": question_label,
                "Question Type": final_question_type,
                "Error Display": "✅ OK"
            })
        else:
            display_text = " | ".join(error_messages)
            if '❌' not in display_text:
                display_text = display_text.replace('⚠', '⚠ ')

            results.append({
                "Question Label": question_label,
                "Question Type": final_question_type,
                "Error Display": display_text
            })
    return results

@app.route("/", methods=["GET", "POST", "HEAD"])
def upload_file():
    if request.method == "HEAD":
        return "", 200

    if request.method == "POST":
        file = request.files.get("file")
        if not file:
            return render_template("upload.html", error="No file uploaded.")

        filename = file.filename.lower()
        content = file.read()
        questions = []

        try:
            if filename.endswith(".xml") or filename.endswith(".txt"):
                questions = list(parse_questions_from_xml(content))
            else:
                return render_template("upload.html", error="Only XML or TXT files supported.")

            if not questions:
                return render_template('upload.html', error='No supported questions found.'), 400
            results_list = run_validations(questions)
            # Always encode the FULL results list for the download form
            full_results_data = base64.b64encode(json.dumps(results_list).encode()).decode()

            return render_template(
                "upload.html",
                message="Validation complete. Results shown.",
                results=results_list,
                full_results_data=full_results_data,
            )

        except Exception as e:
            return render_template("upload.html", error=f"Error processing file: {e}")

    return render_template("upload.html")

@app.route("/download", methods=["POST"])
def download_excel():
    encoded = request.form.get("data")
    filter_active_str = request.form.get("filter_active", "false") # Get toggle state

    if not encoded:
        return "No data to download", 400

    try:
        results_list = json.loads(base64.b64decode(encoded, validate=True).decode())
        if not isinstance(results_list, list) or len(results_list) > 10000:
            raise ValueError()
        expected = {'Question Label', 'Question Type', 'Error Display'}
        for row in results_list:
            if not isinstance(row, dict) or set(row) != expected:
                raise ValueError()
            for key, value in row.items():
                if not isinstance(value, str) or len(value) > 10000:
                    raise ValueError()
                # Keep user-controlled strings from becoming spreadsheet formulas.
                if value.lstrip().startswith(('=', '+', '-', '@')):
                    row[key] = "'" + value
    except (ValueError, TypeError, UnicodeError):
        abort(400, description='Invalid report data.')

    # Filter the results list based on the toggle state if necessary
    filter_active = filter_active_str.lower() == "true"
    if filter_active:
        data_to_download = [
            row for row in results_list if "❌" in row["Error Display"] or "⚠" in row["Error Display"]
        ]
    else:
        data_to_download = results_list

    output = io.BytesIO()
    pd.DataFrame(data_to_download).to_excel(output, engine="openpyxl", index=False, sheet_name="Validation_Results")
    output.seek(0)
    return send_file(output, download_name="validation_results.xlsx", as_attachment=True)

if __name__ == "__main__":
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '5000')), debug=False)