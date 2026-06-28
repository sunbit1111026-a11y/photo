#!/usr/bin/env python3
"""ComfyUI 圖片修改服務 - 免費版"""
import os
import uuid
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import threading
import shutil

# ==================== 設定 ====================
load_dotenv()
app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

COMFYUI_URL = os.environ.get('COMFYUI_URL', 'http://127.0.0.1:8188')
FREE_USE = True  # 免費使用
PORT = int(os.environ.get('PORT', 5000))
COMFYUI_INPUT_DIR = os.environ.get('COMFYUI_INPUT_DIR', '/tmp/comfyui_input')

# 記憶體儲存
orders = {}
cooldown_records = {}  # IP -> last_submit_time
COOLDOWN_SECONDS = 600  # 10 分鐘

# ==================== 50-Qwe-Image-2511 多LoRA切換工作流 ====================
def get_img2img_workflow(image_filename, prompt_text, negative_prompt, denoise=1.0, lora_index=0, image2_filename=None):
    """
    Qwen-Image-2511 多LoRA切換工作流 (支援雙圖輸入)
    image1: 角色原檔 (載入到 image1)
    image2: 參考服飾/配件圖 (載入到 image2) - 可選
    
    參數:
        image_filename: 角色原檔檔名
        image2_filename: 服飾/配件參考圖檔名 (可選)
        prompt_text: 正提示詞 (敘事內容)
        negative_prompt: 負提示詞
        denoise: 降噪強度
        lora_index: LoRA 切換索引 (0=預設, 1=透明人, 2=增大胸部, 3=動漫轉真人, 4=3D手辦)
    """
    import random
    seed_val = random.randint(0, 999999999999)
    
    workflow = {
        # === 模型載入 ===
        "113": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "Qwen-image\\2511\\qwen_image_edit_2511_fp8mixed.safetensors",
                "weight_dtype": "default"
            }
        },
        "84": {
            "class_type": "VAELoader",
            "inputs": {
                "vae_name": "Qwen-image\\qwen_image_vae.safetensors"
            }
        },
        "83": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "Qwen-image\\qwen_2.5_vl_7b_fp8_scaled.safetensors",
                "type": "qwen_image",
                "device": "default"
            }
        },
        
        # === LoRA 載入器 (正確路徑對照 ComfyUI) ===
         "208": {
             "class_type": "LoraLoaderModelOnly",
             "inputs": {
                 "model": ["113", 0],
                 "lora_name": "2511\\Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors",
                 "strength_model": 1.0
             }
         },
         "108": {
             "class_type": "LoraLoaderModelOnly",
             "inputs": {
                 "model": ["113", 0],
                 "lora_name": "2511\\QWEN-IMAGE-EDIT-2511-INVISIBLE-v0.1-AlphaPreview-QQQQ4413.safetensors",
                 "strength_model": 1.0
             }
         },
         "110": {
             "class_type": "LoraLoaderModelOnly",
             "inputs": {
                 "model": ["113", 0],
                 "lora_name": "2511\\One-click breast enhancement_p.safetensors",
                 "strength_model": 0.3
             }
         },
         "112": {
             "class_type": "LoraLoaderModelOnly",
             "inputs": {
                 "model": ["113", 0],
                 "lora_name": "2511\\girlToRealism_20260119_140423.safetensors",
                 "strength_model": 1.0
             }
         },
         "207": {
             "class_type": "LoraLoaderModelOnly",
             "inputs": {
                 "model": ["113", 0],
                 "lora_name": "2511\\QWEN_EDIT_ACTION_V1.safetensors",
                 "strength_model": 1.0
             }
         },
        
        # === LoRA 切換 (easy anythingIndexSwitch) ===
        # index=0 選 Lightning, 1=透明人, 2=增大胸部, 3=動漫轉真人, 4=3D手辦
        "166": {
            "class_type": "easy anythingIndexSwitch",
            "inputs": {
                "value0": ["208", 0],
                "value1": ["108", 0],
                "index": lora_index,
                "value2": ["110", 0],
                "value3": ["112", 0],
                "value4": ["207", 0]
            }
        },
        
        # === 模型處理鏈 ===
        "186": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {
                "shift": 3.01,
                "model": ["166", 0]
            }
        },
        "203": {
            "class_type": "CFGNorm",
            "inputs": {
                "model": ["186", 0],
                "strength": 1.0
            }
        },
        "114": {
            "class_type": "XB_UNetBlockSwap",
            "inputs": {
                "unet_model": ["203", 0],
                "blocks_to_swap": 60
            }
        },
        "115": {
            "class_type": "XB_SageAttentionAccelerator",
            "inputs": {
                "model": ["114", 0],
                "preset": "内置模式 A (128x128x32)"
            }
        },
        
        # === 客戶圖片輸入流程 ===
        "220": {
            "class_type": "LoadImage",
            "inputs": {
                "image": image_filename
            }
        },
        "215": {
             "class_type": "FluxKontextImageScale",
             "inputs": {
                 "image": ["220", 0]
             }
         },
         "221": {
              "class_type": "LoadImage",
              "inputs": {
                  "image": image2_filename if image2_filename else "empty.png"
              }
          },
          "216": {
              "class_type": "FluxKontextImageScale",
              "inputs": {
                  "image": ["221", 0]
              }
          },
        
          # === 提示詞編碼 (使用 TextEncodeQwenImageEditPlus) ===
          "217": {
              "class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {
                  "clip": ["83", 0],
                  "vae": ["84", 0],
                  "image1": ["215", 0],
                  "image2": ["216", 0],
                  "prompt": prompt_text
              }
          },
          "201": {
              "class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {
                  "clip": ["83", 0],
                  "vae": ["84", 0],
                  "image1": ["215", 0],
                  "image2": ["216", 0],
                  "prompt": negative_prompt
              }
          },
        
        # === 參考 latent 方法 ===
        "211": {
            "class_type": "FluxKontextMultiReferenceLatentMethod",
            "inputs": {
                "conditioning": ["217", 0],
                "reference_latents_method": "index_timestep_zero"
            }
        },
        "212": {
            "class_type": "FluxKontextMultiReferenceLatentMethod",
            "inputs": {
                "conditioning": ["201", 0],
                "reference_latents_method": "index_timestep_zero"
            }
        },
        
        # === 圖片編碼為 latent ===
        "200": {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": ["215", 0],
                "vae": ["84", 0]
            }
        },
        
        # === KSampler 生成 ===
        "179": {
            "class_type": "XB_ROCmKSampler",
            "inputs": {
                "model": ["115", 0],
                "positive": ["211", 0],
                "negative": ["212", 0],
                "latent": ["200", 0],
                "seed": seed_val,
                "steps": 4,
                "cfg": 1.0,
                "sampler": "euler",
                "scheduler": "simple",
                "denoise": denoise,
                "cleanup": "单次缓存清理"
            }
        },
        
        # === VAE 解碼 ===
        "123": {
            "class_type": "XB_ROCmVAEDecode",
            "inputs": {
                "samples": ["179", 0],
                "vae": ["84", 0],
                "tile": 448,
                "overlap": 32,
                "cleanup": "不做任何清理"
            }
        },
        
        # === 儲存結果 ===
        "101": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["123", 0],
                "filename_prefix": f"output_{uuid.uuid4().hex[:8]}"
            }
        },
    }
    return workflow

# ==================== API Routes ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    comfy_ok = False
    try:
        r = requests.get(f'{COMFYUI_URL}/history', timeout=5)
        if r.status_code == 200:
            comfy_ok = True
    except:
        pass
    
    return jsonify({
        'status': 'ok',
        'comfyui_connected': comfy_ok,
        'comfyui_url': COMFYUI_URL,
        'free_use': FREE_USE
    })

@app.route('/api/cooldown_check')
def cooldown_check():
    """檢查當前 IP 是否在冷卻時間內"""
    client_ip = request.remote_addr or 'unknown'
    now = time.time()

    if client_ip in cooldown_records:
        elapsed = now - cooldown_records[client_ip]
        if elapsed < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - elapsed
            return jsonify({
                'cooldown_active': True,
                'remaining': remaining,
                'remaining_seconds': int(remaining),
                'remaining_display': f'{int(remaining // 60)} 分 {int(remaining % 60)} 秒後可再使用'
            })
        else:
            del cooldown_records[client_ip]

    return jsonify({
        'cooldown_active': False,
        'remaining': 0,
        'remaining_seconds': 0,
        'remaining_display': '可以立即使用'
    })

@app.route('/api/upload', methods=['POST'])
def upload_image():
    """上傳圖片到 ComfyUI input 資料夾"""
    if 'image' not in request.files:
        return jsonify({'error': '沒有圖片'}), 400
    
    img = request.files['image']
    if img.filename == '':
        return jsonify({'error': '空的檔案名'}), 400
    
    # 儲存圖片到本地 input_images
    save_dir = os.path.join(os.path.dirname(__file__), 'input_images')
    os.makedirs(save_dir, exist_ok=True)
    
    filename = f"upload_{uuid.uuid4().hex[:8]}_{img.filename}"
    filepath = os.path.join(save_dir, filename)
    
    try:
        img.save(filepath)
        
       # 上傳到 ComfyUI 的 input 目錄 (讓 LoadImage 能讀到)
        comfy_input_dir = COMFYUI_INPUT_DIR
        os.makedirs(comfy_input_dir, exist_ok=True)
        
        # 生成唯一檔名避免覆蓋
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        comfy_filename = f"upload_{timestamp}_{img.filename}"
        comfy_filepath = os.path.join(comfy_input_dir, comfy_filename)
        shutil.copy2(filepath, comfy_filepath)
        
        return jsonify({
            'filename': filename,
            'comfy_filename': comfy_filename,
            'url': f'/input_images/{filename}'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload_secondary', methods=['POST'])
def upload_secondary_image():
    """上傳第二張圖片 (服飾/配件參考圖) 到 ComfyUI input 資料夾"""
    if 'image' not in request.files:
        return jsonify({'error': '沒有圖片'}), 400
    
    img = request.files['image']
    if img.filename == '':
        return jsonify({'error': '空的檔案名'}), 400
    
    # 儲存圖片到本地 input_images
    save_dir = os.path.join(os.path.dirname(__file__), 'input_images')
    os.makedirs(save_dir, exist_ok=True)
    
    filename = f"upload_secondary_{uuid.uuid4().hex[:8]}_{img.filename}"
    filepath = os.path.join(save_dir, filename)
    
    try:
        img.save(filepath)
        
        # 上傳到 ComfyUI 的 input 目錄
        comfy_input_dir = COMFYUI_INPUT_DIR
        os.makedirs(comfy_input_dir, exist_ok=True)
        
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        comfy_filename = f"secondary_{timestamp}_{img.filename}"
        comfy_filepath = os.path.join(comfy_input_dir, comfy_filename)
        shutil.copy2(filepath, comfy_filepath)
        
        return jsonify({
            'filename': filename,
            'comfy_filename': comfy_filename,
            'url': f'/input_images/{filename}'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/submit', methods=['POST'])
def submit_order():
    """提交修改需求"""
    data = request.json
    image_filename = data.get('image_filename')
    secondary_filename = data.get('secondary_filename')  # 第二張圖片 (服飾/配件參考圖)
    prompt_text = data.get('prompt', '')
    negative_prompt = data.get('negative_prompt', 'lowres, bad anatomy, worst quality, blur')
    denoise = float(data.get('denoise', '0.75'))
    
    if not image_filename or not prompt_text:
        return jsonify({'error': '需要圖片和描述'}), 400
    
    order_id = str(uuid.uuid4())[:8]
    
    order = {
        'id': order_id,
        'image_filename': image_filename,
        'secondary_filename': secondary_filename,  # 第二張圖片
        'prompt': prompt_text,
        'negative_prompt': negative_prompt,
        'denoise': denoise,
        'status': 'processing',
        'created_at': datetime.now().isoformat(),
        'result_url': None,
        'prompt_id': None,
        'error': None
    }
    orders[order_id] = order
    
    # 記錄 IP 冷卻時間
    client_ip = request.remote_addr or 'unknown'
    cooldown_records[client_ip] = time.time()
    
    # 啟動背景處理
    threading.Thread(target=process_img2img, args=(order_id,), daemon=True).start()
    
    return jsonify({
        'order_id': order_id,
        'status': 'processing'
    })

@app.route('/api/order/<order_id>/status')
def order_status(order_id):
    order = orders.get(order_id)
    if not order:
        return jsonify({'error': '訂單不存在'}), 404
    
    # 如果還在處理中，檢查 ComfyUI
    if order['status'] == 'processing' and order.get('prompt_id'):
        progress = check_comfyui(order['prompt_id'])
        if progress.get('done'):
            order['status'] = 'completed'
            order['result_url'] = progress.get('result_url')
        elif progress.get('error'):
            order['status'] = 'failed'
            order['error'] = progress['error']
    
    return jsonify({
        'order_id': order_id,
        'status': order['status'],
        'prompt': order.get('prompt'),
        'result_url': order.get('result_url'),
        'error': order.get('error'),
        'created_at': order['created_at']
    })

@app.route('/api/order/<order_id>/download')
def download_result(order_id):
    order = orders.get(order_id)
    if not order or order['status'] != 'completed' or not order.get('result_url'):
        return jsonify({'error': '結果不存在或未完成'}), 404
    
    try:
        r = requests.get(order['result_url'])
        if r.status_code == 200:
            from flask import Response
            return Response(
                r.content,
                mimetype='image/png',
                headers={'Content-Disposition': f'inline; filename=result_{order_id}.png'}
            )
        else:
            return jsonify({'error': '下載失敗'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== ComfyUI 處理 ====================

def check_comfyui(prompt_id):
    """檢查 ComfyUI 任務狀態"""
    try:
        r = requests.get(f'{COMFYUI_URL}/history', timeout=10)
        if r.status_code == 200:
            history = r.json()
            if prompt_id in history:
                data = history[prompt_id]
                # 檢查是否有輸出
                outputs = data.get('outputs', {})
                for node_id, node_data in outputs.items():
                    if 'images' in node_data and node_data['images']:
                        img_info = node_data['images'][0]
                        result_url = (
                            f'{COMFYUI_URL}/view?'
                            f'filename={img_info["filename"]}'
                            f'&subfolder={img_info["subfolder"]}'
                            f'&type={img_info["type"]}'
                        )
                        return {'done': True, 'result_url': result_url}
                
                # 檢查是否完成但無輸出
                status = data.get('status', {})
                if status.get('completed') and status.get('status_str') == 'success':
                    return {'done': True, 'result_url': None}
                
                return {'done': False}
    except:
        pass
    return {'done': False}

def process_img2img(order_id):
    """處理 img2img 任務"""
    order = orders.get(order_id)
    if not order:
        return
    
    print(f'[處理] 訂單 {order_id} 開始')
    
    try:
        # 讀取 workflow
        workflow = get_img2img_workflow(
            order['image_filename'],
            order['prompt'],
            order.get('negative_prompt', 'lowres, bad anatomy'),
            order.get('denoise', 0.75),
            image2_filename=order.get('secondary_filename')  # 第二張圖片 (服飾/配件參考圖)
        )
        
        # 提交到 ComfyUI
        payload = {
            'prompt': workflow,
            'client_id': order_id
        }
        
        r = requests.post(f'{COMFYUI_URL}/prompt', json=payload, timeout=30)
        
        if r.status_code == 200:
            result = r.json()
            order['prompt_id'] = result.get('prompt_id')
            print(f'[處理] 訂單 {order_id} 已提交 prompt_id={order["prompt_id"]}')
            
            # 輪詢等待完成 (最多 3 分鐘)
            max_wait = 180
            start = time.time()
            
            while time.time() - start < max_wait:
                progress = check_comfyui(order['prompt_id'])
                
                if progress.get('done'):
                    if progress.get('result_url'):
                        order['status'] = 'completed'
                        order['result_url'] = progress['result_url']
                        print(f'[完成] 訂單 {order_id} 處理完成')
                    else:
                        order['status'] = 'failed'
                        order['error'] = '處理完成但無輸出'
                        print(f'[失敗] 訂單 {order_id} 無輸出')
                    return
                elif progress.get('error'):
                    order['status'] = 'failed'
                    order['error'] = progress['error']
                    print(f'[失敗] 訂單 {order_id}: {progress["error"]}')
                    return
                
                time.sleep(5)
            
            order['status'] = 'failed'
            order['error'] = '處理超時 (3分鐘)'
            print(f'[超時] 訂單 {order_id}')
            
        else:
            order['status'] = 'failed'
            order['error'] = f'提交失敗: {r.text[:200]}'
            print(f'[提交失敗] 訂單 {order_id}: {r.text[:200]}')
            
    except requests.exceptions.ConnectionError:
        order['status'] = 'failed'
        order['error'] = '無法連線 ComfyUI，請確認服務已啟動'
        print(f'[連線錯誤] 無法連線 ComfyUI')
    except Exception as e:
        order['status'] = 'failed'
        order['error'] = str(e)
        print(f'[錯誤] 訂單 {order_id}: {e}')

# ==================== 啟動 ====================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
    port = int(os.environ.get('FLASK_PORT', '5000'))
    print(f'🚀 服務啟動於 http://{host}:{port}')
    print(f'💻 ComfyUI: {COMFYUI_URL}')
    print(f'💰 模式: 免費使用')
    
    app.run(host=host, port=port, debug=True)
