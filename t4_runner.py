# 文件名: t4_runner.py (部署在 T4 算力服务器上)

from flask import Flask, request, jsonify
import io
import contextlib
import logging
import json # 确保导入 json 库

app = Flask(__name__)
# 配置日志，便于在服务器上查看代码执行情况
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# !! 警告：直接使用 exec() 存在安全风险，建议在生产环境中使用 Docker 或 RestrictedPython 进行沙箱隔离 !!
@app.route('/execute', methods=['POST'])
def execute_code():
    """接收代码并执行，返回结果或错误。"""
    try:
        data = request.get_json()
        code_to_run = data.get('code', '')
    except Exception:
        return jsonify({"status": "error", "output": "请求数据格式错误，请发送JSON数据。"})
    
    if not code_to_run:
        return jsonify({"status": "error", "output": "没有提供代码。"})

    # 使用 io.StringIO 和 contextlib.redirect_stdout 捕获 print() 的输出
    f = io.StringIO()
    try:
        logging.info(f"正在执行代码:\n{code_to_run[:100]}...")
        
        # 运行代码。使用空字典作为 globals，防止访问不必要的全局变量。
        with contextlib.redirect_stdout(f):
            exec(code_to_run, {}) 
        
        output = f.getvalue()
        
        # 成功执行，返回 JSON 格式的输出
        return jsonify({
            "status": "success",
            "output": output.strip() if output else "代码执行成功，无输出 (请使用print())"
        })

    except Exception as e:
        # 捕获代码执行中的运行时错误
        error_message = f"{type(e).__name__}: {str(e)}"
        logging.error(f"代码执行失败: {error_message}")
        return jsonify({
            "status": "error",
            "output": f"代码执行失败，错误信息：{error_message}"
        })

if __name__ == '__main__':
    logging.info("T4 Code Runner 服务启动中...")
    # 监听所有 IP 地址的 5000 端口
    # 在生产环境，请使用 Gunicorn/Supervisor 等工具部署，而不是 app.run()
    app.run(host='0.0.0.0', port=5000)