# ComfyUI Z-Image 圖片修改交易平台

## 功能
- 客人上傳圖片、輸入修改需求
- USDT (TRC-20) 支付
- 串接本地 ComfyUI 執行 Z-Image 修改
- 完成後回傳下載

## 快速開始
```bash
pip install -r requirements.txt
python app.py
```

## 環境變數
複製 `.env.example` 到 `.env` 並填寫：
- `COMFYUI_URL`: 你的 ComfyUI 地址 (預設 http://127.0.0.1:8188)
- `TRON_API_KEY`: TronGrid API key
- `YOUR_WALLET`: 收款錢包地址
- `PAYMENT_AMOUNT`: 每次修改費用 (USDT)
