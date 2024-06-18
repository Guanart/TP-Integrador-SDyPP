from datetime import datetime, timezone
import threading
from flask import Flask, request, jsonify
import json
import time

app = Flask(__name__)
workers_alive=[]

@app.route('/alive', methods=["POST"])
def receive_keep_alive():
    global workers_alive
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400
        
        required_fields = ["id"]
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Worker id no proporcionado"}), 400
        
        for worker in workers_alive:
            if worker["id"]==data["id"]:
                worker["last_keep_alive"]= datetime.now(timezone.utc)
                break
        
        return({"message": "Mensaje keep_alive recibido correctamente"}), 200
    except Exception as e:
        return jsonify(e)

@app.route("/register", methods=["POST"])
def register():
    global workers_alive
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400
        
        required_fields = ['id', "type"]
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Faltan uno o más campos necesarios.'}), 400

        workers_alive.append({
            "id": data["id"],
            "type": data["type"],
            'last_keep_alive': datetime.now(timezone.utc),
            'missed_keep_alives': 0
        })
        return jsonify({"message": "Worker registrado correctamente."}), 200
    except Exception as e:
        return jsonify(e)

def remove_worker_by_id(worker_id):
    global workers_alive
    workers_alive = [worker for worker in workers_alive if worker["id"] != worker_id]

def get_len_gpu_workers():
    global workers_alive
    return sum(1 for worker in workers_alive if worker["type"] == "gpu")
    

def workers_with_live():
    global workers_alive
    while True:
        now = datetime.now(timezone.utc)
        for worker in workers_alive:
            time_diference = (now - worker["last_keep_alive"]).total_seconds()
            if time_diference >= 5:
                worker["missed_keep_alives"]+=1
            if worker["missed_keep_alives"]==3:
                remove_worker_by_id(worker["id"])
        if len(workers_alive)<1:
            #levanto workers cpu pool en kubernetes.
            pass
        if get_len_gpu_workers()>=1:
            #bajo los workers cpu de kubernetes.
            pass
        time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=workers_with_live).start()
    app.run(host="0.0.0.0", port=5000)