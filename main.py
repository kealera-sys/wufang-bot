import os
import requests
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from PIL import Image
from io import BytesIO
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageSendMessage, TextSendMessage
import cloudinary
import cloudinary.uploader

# --- 1. Cloudinary 設定 (在 Render 環境變數中設定) ---
cloudinary.config( 
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'), 
    api_key = os.environ.get('CLOUDINARY_API_KEY'), 
    api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
    secure = True
)

app = Flask(__name__)

# --- 2. LINE 資訊 (在 Render 環境變數中設定) ---
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

# --- 3. 工具函式 ---
def get_icon(name, url, size=(120, 120)):
    """下載並處理 1:1 圖示"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        img = Image.open(BytesIO(response.content)).convert("RGBA")
        # 使用最新的 Resampling 方法
        return img.resize(size, Image.Resampling.LANCZOS)
    except Exception as e:
        print(f"圖示下載失敗 ({name}): {e}")
        return Image.new('RGBA', size, (200, 200, 200, 60))

def create_report_img():
    """抓取 Bitfinex 數據並生成專業報表圖片"""
    symbols_info = {
        "fUSD": {"name": "USD", "icon": "https://static.okx.com/cdn/oksupport/asset/currency/icon/usd.png"},
        "fUST": {"name": "USDT", "icon": "https://static.okx.com/cdn/oksupport/asset/currency/icon/usdt.png"},
        "fXAUT": {"name": "XAUT", "icon": "https://static.okx.com/cdn/oksupport/asset/currency/icon/xaut.png"},
        "fBTC": {"name": "BTC", "icon": "https://static.okx.com/cdn/oksupport/asset/currency/icon/btc.png"},
        "fETH": {"name": "ETH", "icon": "https://static.okx.com/cdn/oksupport/asset/currency/icon/eth.png"},
        "fEUR": {"name": "EUR", "icon": "https://static.okx.com/cdn/oksupport/asset/currency/icon/eur.png"}
    }
    
    results = []
    for sym, info in symbols_info.items():
        try:
            resp = requests.get(f"https://api-pub.bitfinex.com/v2/trades/{sym}/hist?limit=1", timeout=5).json()
            rate = float(resp[0][3]) * 100
            results.append({
                "Currency": info['name'], 
                "Daily": f"{rate:.4f}%", 
                "APR": f"{rate*365:.2f}%", 
                "icon": info['icon']
            })
        except:
            results.append({"Currency": info['name'], "Daily": "N/A", "APR": "N/A", "icon": info['icon']})
    
    df = pd.DataFrame(results)
    
    # 繪圖設定
    fig, ax = plt.subplots(figsize=(10, 7), dpi=120)
    ax.axis('off')
    
    # 建立表格
    the_table = ax.table(
        cellText=df[['Currency', 'Daily', 'APR']].values, 
        colLabels=['Currency', 'Daily', 'APR'], 
        loc='center', 
        cellLoc='center', 
        colColours=["#1a1a1a"]*3
    )
    
    the_table.auto_set_font_size(False)
    the_table.set_fontsize(14)
    the_table.scale(1.0, 4.2)
    
    # 表頭顏色設定
    for k, cell in the_table.get_celld().items():
        if k[0] == 0:  # 第一列（表頭）
            cell.get_text().set_color('white')
            cell.get_text().set_weight('bold')
    
    fig.canvas.draw()
    
    # 在表格旁插入圖示
    for i, row in df.iterrows():
        img_icon = get_icon(row['Currency'], row['icon'])
        imagebox = OffsetImage(img_icon, zoom=0.22)
        ab = AnnotationBbox(imagebox, (0.28, 0.745 - (i * 0.117)), frameon=False)
        ax.add_artist(ab)
    
    # 存檔至本地路徑
    report_path = "line_report.png"
    plt.savefig(report_path, bbox_inches='tight', facecolor='white')
    plt.close()
    return report_path

# --- 4. Webhook 邏輯 ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    user_id = event.source.user_id
    
    print(f"收到指令: {user_msg}")

    # 包含「利率」關鍵字即觸發
    if "利率" in user_msg:
        # 第一步：立即回覆文字，讓使用者知道正在處理
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="📊 正在抓取數據並生成報表，請稍候約 3-5 秒...")
        )
        
        try:
            # 第二步：生成圖片報表
            path = create_report_img()
            
            # 第三步：使用 Cloudinary 上傳圖片
            upload_result = cloudinary.uploader.upload(path)
            img_url = upload_result['secure_url']
            print(f"✅ Cloudinary 上傳成功: {img_url}")
            
            # 第四步：推播圖片訊息給使用者
            line_bot_api.push_message(
                user_id,
                ImageSendMessage(original_content_url=img_url, preview_image_url=img_url)
            )
            
        except Exception as e:
            error_msg = f"❌ 報表處理失敗: {str(e)}"
            print(error_msg)
            line_bot_api.push_message(user_id, TextSendMessage(text=error_msg))

if __name__ == "__main__":
    # --- 重要：Render 部署專用端口設定 ---
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)