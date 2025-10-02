# 文件名: ccc.py (VoceChat Webhook + DeepSeek + T4 算力工具)

# coding: utf-8
from flask import Flask, request, jsonify
from openai import OpenAI  # 使用新版的导入方式
import requests
import json
import logging
import re

# --- 1. 请在这里修改您的配置信息 ---
# ===================================================================
# 务必替换为您的 DeepSeek API Key
DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"  
# 务必替换为您 新的 VoceChat Bot API Key
VOCECHAT_BOT_API_KEY = "xxxxxxxxxxxxxxxxxxxxxxxx" 

# !!重要!! 填入您这个新机器人的 User ID (一个数字)
BOT_UID = 9
# 您的 VoceChat 服务器地址
VOCECHAT_DOMAIN = "http://127.0.0.1:3000"

# T4 算力服务器的公网访问地址 (frp 隧道地址)
# 端口 6006 是您在 frpc.ini 中设置的 remote_port
T4_SERVER_URL = "http://xxxxx:6006/execute" 
# ===================================================================


# --- 2. 初始化服务 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
# 使用新版方式初始化 OpenAI 客户端
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# VoceChat API 地址
VOCECHAT_API_URL_USER = f"{VOCECHAT_DOMAIN}/api/bot/send_to_user/{{uid}}"
VOCECHAT_API_URL_GROUP = f"{VOCECHAT_DOMAIN}/api/bot/send_to_group/{{gid}}"


# --- 3. Webhook 核心逻辑 ---
@app.route('/webhook', methods=['POST'])
def vocechat_webhook():
    raw_data = request.get_data(as_text=True)
    logging.info(f"--- 收到新请求 --- \n原始数据: {raw_data}")

    if not raw_data:
        logging.warning("请求体为空")
        return jsonify({"status": "error", "message": "请求体为空"}), 400

    try:
        data = json.loads(raw_data)
        
        detail = data.get('detail', {})
        content_type = detail.get('content_type')

        # 1. 只处理纯文本消息
        if content_type != 'text/plain':
            logging.info(f"忽略非纯文本消息: {content_type}")
            return jsonify({"status": "ignored"}), 200
        
        message_content = detail.get('content', '').strip()
        
        # 2. 判断是私聊还是群聊
        target = data.get('target')
        is_group_chat = target and 'gid' in target

        if is_group_chat:
            # 群聊：必须 @机器人 才回复
            mentions = detail.get('properties', {}).get('mentions', [])
            if BOT_UID not in mentions:
                logging.info("群聊消息，但未 @机器人，忽略")
                return jsonify({"status": "ignored"}), 200
            
            clean_content = re.sub(rf'\s*@{BOT_UID}\s*', '', message_content).strip()
            reply_to_id = target['gid']
            is_reply_to_group = True
            logging.info(f"收到群聊 @消息. 群组ID: {reply_to_id}, 清理后内容: '{clean_content}'")

        else: # 私聊
            clean_content = message_content
            reply_to_id = data.get('from_uid')
            is_reply_to_group = False
            logging.info(f"收到私聊消息. 用户ID: {reply_to_id}, 内容: '{clean_content}'")

        if not clean_content:
            logging.info("内容为空，忽略")
            return jsonify({"status": "ignored"}), 200
            
        # 3. 调用 AI 并发送回复
        ai_response = get_ai_reply(clean_content)
        send_message_to_vocechat(reply_to_id, ai_response, is_reply_to_group)
        
        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"处理出错: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# --- T4 算力服务器代码执行工具 ---
def run_on_t4_server(code: str) -> str:
    """通过 frp 隧道向 T4 服务器发送代码执行请求"""
    headers = {"Content-Type": "application/json"}
    payload = {"code": code}

    try:
        logging.info(f"正在向 T4 服务器 ({T4_SERVER_URL}) 发送代码执行请求...")
        # 请求 T4 服务器的 http://120.55.54.25:6006/execute 接口
        response = requests.post(T4_SERVER_URL, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return json.dumps({
                "status": "success",
                "output": result.get('output', 'N/A')
            })
        else:
            return json.dumps({
                "status": "error",
                "message": f"T4 服务器返回 HTTP 错误: {response.status_code}",
            })

    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "message": f"连接 T4 服务器失败: {str(e)}"})

# --- 工具列表和定义 ---
TOOLS_AVAILABLE = {
    "run_on_t4_server": run_on_t4_server,
}

TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "run_on_t4_server",
            "description": "当用户请求运行任何Python代码、进行复杂计算或需要使用T4 GPU资源时，调用此工具。代码输出将作为结果返回，要求代码使用 print() 函数输出结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要执行的Python代码块，例如 'import torch; print(torch.cuda.is_available())'。"
                    }
                },
                "required": ["code"]
            }
        }
    }
]


# --- 4. 辅助函数 (已修改 get_ai_reply 以支持工具调用) ---
def get_ai_reply(text):
    """使用新版 openai 库调用 AI，支持工具调用"""
    messages = [{"role": "user", "content": text}]
    
    try:
        # 第一轮：尝试获取 DeepSeek 的回复或工具调用请求
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS_DEFINITION, # 传入工具列表
        )
        
        # 检查是否有工具调用请求
        if response.choices[0].message.tool_calls:
            messages.append(response.choices[0].message) # 添加 AI 的工具请求到历史记录
            tool_calls = response.choices[0].message.tool_calls
            
            # 循环执行所有工具调用
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                
                if function_name in TOOLS_AVAILABLE:
                    function_to_call = TOOLS_AVAILABLE[function_name]
                    function_args = json.loads(tool_call.function.arguments)
                    
                    # 执行本地函数 (run_on_t4_server)
                    function_response = function_to_call(**function_args)
                    logging.info(f"工具 '{function_name}' 执行结果: {function_response}")
                    
                    # 将工具执行结果作为新消息添加到历史记录
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": function_response,
                    })
                else:
                    logging.error(f"找不到工具: {function_name}")
            
            # 第二轮：将工具执行结果发回 DeepSeek，获取最终回复
            second_response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages
            )
            return second_response.choices[0].message.content

        else:
            # 没有工具调用，返回 DeepSeek 的回复
            return response.choices[0].message.content

    except Exception as e:
        logging.error(f"调用 DeepSeek API 或工具失败: {e}", exc_info=True)
        return "抱歉，我在处理您的请求时遇到了内部错误，请检查日志。"

def send_message_to_vocechat(target_id, text, is_group=False):
    """发送消息到 VoceChat"""
    headers = {"x-api-key": VOCECHAT_BOT_API_KEY, "Content-Type": "text/plain"}
    
    if is_group:
        url = VOCECHAT_API_URL_GROUP.format(gid=target_id)
        log_msg = f"发送消息到 VoceChat 群组 {target_id}"
    else:
        url = VOCECHAT_API_URL_USER.format(uid=target_id)
        log_msg = f"发送消息到 VoceChat 用户 {target_id}"

    try:
        res = requests.post(url, headers=headers, data=text.encode('utf-8'))
        logging.info(f"{log_msg}: 状态码={res.status_code}, 响应体={res.text}")
    except Exception as e:
        logging.error(f"{log_msg} 失败: {e}")


# --- 5. 启动服务 ---
if __name__ == '__main__':
    # !!! 关键变更：使用新的端口 25000 !!!
    app.run(host='0.0.0.0', port=25000)


