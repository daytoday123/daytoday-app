import streamlit as st
import pandas as pd
import openai
from rapidfuzz import fuzz
import easyocr
from collections import defaultdict
from PIL import Image
import io
from streamlit_cropper import st_cropper
import socket

# === OPENAI SETUP ===
openai.api_key = "your-api-key-here"

# === EasyOCR SETUP ===
reader = easyocr.Reader(['en'], gpu=False)

# === CHECK INTERNET ===
def check_internet():
    try:
        socket.create_connection(("1.1.1.1", 53))
        return True
    except OSError:
        return False

# === ALIAS DICTIONARY ===
def build_alias_dictionary(item_names):
    prefix_map = defaultdict(set)
    for name in item_names:
        clean_name = name.replace(" ", "")
        for length in range(2, 5):
            if len(clean_name) >= length:
                prefix_map[clean_name[:length]].add(name)
        for word in name.split():
            if len(word) >= 4:
                for i in range(2, min(len(word) + 1, 5)):
                    prefix_map[word[:i]].add(word)
    return {k: list(v)[0] for k, v in prefix_map.items() if len(v) == 1}

def apply_aliases(query, alias_dict):
    words = query.split()
    return ' '.join([alias_dict.get(word, word) for word in words])

def gpt_correct_query(query):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": f"Correct and complete this grocery product name:\nInput: {query}\nOutput:"}],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return query

def fuzzy_match(query, item_names, df, user_mrp=None):
    query_keywords = query.split()
    matches = []
    for name in item_names:
        text_score = (
            fuzz.token_set_ratio(query, name) * 0.4 +
            fuzz.partial_ratio(query, name) * 0.3 +
            fuzz.token_sort_ratio(query, name) * 0.3
        )
        row = df[df['ITEM NAME'] == name].iloc[0]
        product_mrp = row['MRP'] if 'MRP' in row else 0
        mrp_score = 0
        if user_mrp:
            try:
                product_mrp = float(product_mrp)
                user_mrp = float(user_mrp)
                if abs(product_mrp - user_mrp) <= 0.2 * user_mrp:
                    mrp_score = 20
            except:
                pass
        total_score = text_score + mrp_score
        matches.append((name, total_score))
    return sorted(matches, key=lambda x: x[1], reverse=True)

def run_search(query, df, item_names, alias_dict, user_mrp=None):
    query = gpt_correct_query(query).lower()
    query = apply_aliases(query, alias_dict)
    matches = fuzzy_match(query, item_names, df, user_mrp)

    top_matches = []
    for name, score in matches[:20]:
        row = df[df['ITEM NAME'] == name].iloc[0]
        top_matches.append({
            "ITEM NAME": name.upper(),
            "MRP": row['MRP'],
            "BARCODE": row['BARCODE'] if 'BARCODE' in row else '',
            "COMPANY": row['COMPANY'] if 'COMPANY' in row else '',
            "GROUP": row['GROUP'] if 'GROUP' in row else '',
            "Match %": round(score, 1)
        })

    brand_matches = []
    query_keywords = query.split()
    if query_keywords:
        main_term = query_keywords[0]
        for name in item_names:
            score = fuzz.ratio(main_term, name)
            row = df[df['ITEM NAME'] == name].iloc[0]
            brand_matches.append({
                "ITEM NAME": name.upper(),
                "MRP": row['MRP'],
                "BARCODE": row['BARCODE'] if 'BARCODE' in row else '',
                "COMPANY": row['COMPANY'] if 'COMPANY' in row else '',
                "GROUP": row['GROUP'] if 'GROUP' in row else '',
                "Match %": round(score, 1)
            })
        brand_matches = sorted(brand_matches, key=lambda x: x['Match %'], reverse=True)[:20]

    return top_matches, brand_matches

# === STREAMLIT UI ===
st.set_page_config(page_title="Fuzzy Product Search", layout="wide")
st.title("🛒 Product Search with AI + Fuzzy Match")

# Show internet connection status
if check_internet():
    st.markdown("<span style='color:green'>🟢 Online Mode: Internet Connected</span>", unsafe_allow_html=True)
else:
    st.markdown("<span style='color:red'>🔴 Offline Mode: No Internet Detected</span>", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Upload your product list Excel file", type=["xlsx"])

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    df = df.fillna("")
    df['ITEM NAME'] = df['ITEM NAME'].astype(str).str.lower().str.strip()
    item_names = df['ITEM NAME'].tolist()
    alias_dict = build_alias_dictionary(item_names)

    st.markdown("### 🔍 Text Search")
    text_input = st.text_input("Enter product name")
    user_mrp = st.text_input("Enter MRP (optional, for +/- 20% match)")
    if text_input:
        top_matches, brand_matches = run_search(text_input, df, item_names, alias_dict, user_mrp)
        st.subheader("📋 Top 20 Smart Matches")
        st.dataframe(pd.DataFrame(top_matches))
        st.subheader("🔎 Top 20 Brand-Like Matches")
        st.dataframe(pd.DataFrame(brand_matches))

    st.markdown("### 📸 Image Search with Cropping")
    image_files = st.file_uploader("Upload up to 2 product photos", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
    if image_files:
        combined_text = []
        for img in image_files:
            st.image(img, caption="Uploaded Image", use_column_width=True)
            st.write("✂️ Adjust crop area below")
            cropped_img = st_cropper(Image.open(img), box_color='#FF0000', aspect_ratio=None, return_type='image', realtime_update=False)
            buf = io.BytesIO()
            cropped_img.save(buf, format="PNG")
            result = reader.readtext(buf.getvalue())
            extracted_text = ' '.join([line[1] for line in result])
            combined_text.append(extracted_text)

        combined_query = ' '.join(combined_text)
        corrected_text = st.text_input("📝 Modify OCR Result if needed", value=combined_query)
        text_mrp = st.text_input("💰 Enter MRP for photo-based search (optional)")
        top_matches, brand_matches = run_search(corrected_text, df, item_names, alias_dict, text_mrp)
        st.subheader("📋 Top 20 Smart Matches")
        st.dataframe(pd.DataFrame(top_matches))
        st.subheader("🔎 Top 20 Brand-Like Matches")
        st.dataframe(pd.DataFrame(brand_matches))
