import os
import sys
import json
import base64
import time
import urllib.request
import urllib.error
import re

"""
Photo Geolocator for make.fun.

This module automates the geolocation of street-level photos by analyzing visual clues
using a two-model strategy to optimize accuracy and budget efficiency:
1. Primary Model: `gpt-6-sol` for high-capability analysis.
2. Fallback Model: `gpt-6-luna` used if the primary model fails or is refused.

Photos are processed in order of increasing byte size to manage budget consumption.
"""

# Constants from spec
MODEL_PRIMARY = 'gpt-6-sol'
MODEL_FALLBACK = 'gpt-6-luna'
PROMPT = (
    "Look at the street-level photo and place it on Earth. "
    "Reason briefly about the visible clues (language and script on signs, "
    "which side of the road traffic drives on, vegetation and climate, "
    "architecture and building style, road markings and license plates, "
    "terrain, sun position). "
    "Then name its best guess of country, region and city. "
    "Then give ONE latitude and longitude as the last line, exactly as JSON: "
    '{"lat": <degrees north>, "lon": <degrees east>}. '
    "Always give your best guess, never refuse, never give a range, "
    "never give more than one coordinate pair."
)
MAX_TOKENS = 768
RETRIES = 3

def get_env_var(name):
    val = os.environ.get(name)
    if not val:
        raise ValueError(f"{name} is not set")
    return val

def request_with_retry(url, method='GET', data=None, headers=None):
    if headers is None:
        headers = {}
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read(), response.status
        except urllib.error.HTTPError as e:
            if attempt < RETRIES and e.code in [408, 429, 500, 502, 503, 504]:
                time.sleep(2 * (attempt + 1))
                continue
            raise e
        except Exception as e:
            if attempt < RETRIES:
                time.sleep(2 * (attempt + 1))
                continue
            raise e
    raise Exception("Max retries exceeded")

def parse_coordinates(text):
    # Find last JSON object
    matches = list(re.finditer(r'\{[^{}]*\}', text))
    for match in reversed(matches):
        try:
            o = json.loads(match.group(0))
            lat = o.get('lat') if o.get('lat') is not None else o.get('latitude')
            lon = o.get('lon') if o.get('lon') is not None else (o.get('lng') if o.get('lng') is not None else o.get('longitude'))
            
            if lat is not None and lon is not None and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return lat, lon
        except:
            continue
            
    # Fallback to numbers
    nums = [float(n) for n in re.findall(r'-?\d+(?:\.\d+)?', text)]
    for i in range(len(nums) - 1):
        lat, lon = nums[i], nums[i+1]
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return None

def ask_model(model, jpeg_bytes, base_url, api_key):
    url = f"{base_url}/v1/chat/completions"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    
    encoded_image = base64.b64encode(jpeg_bytes).decode('utf-8')
    
    body = {
        "model": model,
        "max_completion_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}}
                ]
            }
        ]
    }
    
    try:
        response_body, _ = request_with_retry(url, method='POST', data=json.dumps(body).encode('utf-8'), headers=headers)
        res_data = json.loads(response_body.decode('utf-8'))
        return res_data['choices'][0]['message']['content']
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"Model call refused (HTTP {e.code})\n")
        return None
    except Exception as e:
        sys.stderr.write(f"Model call failed: {e}\n")
        return None

def main():
    env_url = get_env_var('MAKEFUN_ENV_URL').rstrip('/')
    base_url = get_env_var('OPENAI_BASE_URL').rstrip('/')
    api_key = get_env_var('OPENAI_API_KEY')
    
    # 1. Fetch photos
    try:
        photos_data, _ = request_with_retry(f"{env_url}/photos")
    except Exception as e:
        sys.stderr.write(f"Failed to fetch initial photo list: {e}\n")
        sys.exit(1)
        
    all_photos = json.loads(photos_data.decode('utf-8'))['photos']
    
    # Store original order
    original_photos = all_photos
    
    # Sort for processing
    photos_to_process = sorted([p for p in all_photos if not p.get('answered', False)], key=lambda x: x['bytes'])
    
    results = {} # id -> (lat, lon)
    use_fallback = False
    
    for p in photos_to_process:
        sys.stderr.write(f"Processing photo {p['id']}...\n")
        
        try:
            jpeg_bytes, _ = request_with_retry(f"{env_url}{p['url']}")
        except Exception as e:
            sys.stderr.write(f"Failed to fetch photo {p['id']}, skipping: {e}\n")
            continue
        
        model = MODEL_FALLBACK if use_fallback else MODEL_PRIMARY
        
        text = ask_model(model, jpeg_bytes, base_url, api_key)
        
        if text is None and not use_fallback:
            # Try fallback immediately if primary fails
            sys.stderr.write("Primary model failed, switching to fallback.\n")
            use_fallback = True
            text = ask_model(MODEL_FALLBACK, jpeg_bytes, base_url, api_key)
            
        if text:
            coords = parse_coordinates(text)
            if coords:
                results[p['id']] = coords
                sys.stderr.write(f"Answer found for {p['id']}: {coords}\n")
            else:
                sys.stderr.write(f"No coordinates found for {p['id']}\n")
        else:
            sys.stderr.write(f"Failed to get answer for {p['id']}\n")
            
    # Post answers in original order
    answers_to_post = []
    for p in original_photos:
        if p['id'] in results:
            answers_to_post.append({
                "id": p['id'],
                "lat": results[p['id']][0],
                "lon": results[p['id']][1]
            })
            
    if not answers_to_post:
        sys.stderr.write("No answers collected.\n")
        sys.exit(1)
        
    try:
        request_with_retry(f"{env_url}/answers", method='POST', data=json.dumps({"answers": answers_to_post}).encode('utf-8'), headers={'Content-Type': 'application/json'})
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"Failed to post answers: {e}\n")
        sys.exit(1)

if __name__ == '__main__':
    main()
